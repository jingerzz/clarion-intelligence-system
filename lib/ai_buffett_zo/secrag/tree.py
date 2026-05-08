"""Hierarchical filing tree built via /zo/ask summaries.

For v1 we keep the tree shallow (max 2 levels):
  FilingTree
    └── SectionNode      (one per curated section: business, risk_factors, mdna, ...)
          └── ChunkNode  (only when section text exceeds max_chunk_tokens)

A SectionNode's `summary` is taken from a single LLM call when the section fits
under the chunk budget, or synthesized from its chunks' summaries otherwise.

Token counting is rough — we use len(text) // 4 as a proxy. Good enough for
chunk sizing; the actual model context is far larger than any chunk we produce.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ai_buffett_zo.llm import (
    DEFAULT_MODEL_INDEX,
    ZoClient,
    schemas,
)
from ai_buffett_zo.secrag.loader import FilingMetadata
from ai_buffett_zo.secrag.sections import Section

DEFAULT_MAX_CHUNK_TOKENS = 4000  # well under any model's context; ~16k chars
RAW_INDEX_TOKEN_LIMIT = 15_000   # safety net: a "raw" filing this long gets full indexing


@dataclass
class ChunkNode:
    """A piece of a section that was too big to summarize whole."""

    chunk_index: int
    text: str
    summary: str
    summary_data: dict[str, Any]


@dataclass
class SectionNode:
    """One curated section. `chunks` is empty when section fit under the budget."""

    label: str
    title: str
    text: str
    summary: str
    summary_data: dict[str, Any]
    chunks: list[ChunkNode] = field(default_factory=list)


@dataclass(frozen=True)
class FilingTree:
    """Indexed tree for one filing."""

    metadata: FilingMetadata
    sections: list[SectionNode]
    indexed_at: datetime
    indexer_model: str


# Sentinel model name used by build_raw_tree — distinguishes raw-stored filings
# from LLM-summarized ones in `~/clarion/sec/{TICKER}/{accession}.meta.json`.
RAW_INDEXER_MODEL: str = "raw-no-llm"


def build_raw_tree(metadata: FilingMetadata, sections: list[Section]) -> FilingTree:
    """Build a FilingTree without any LLM calls.

    For short filings (8-K, Form 4, etc.) where summarization is wasteful and
    the entire content is small enough to keyword-search directly. The text is
    preserved verbatim per section; summary fields are empty.

    Routing decision (full LLM tree vs raw) is made by the indexer using
    secrag.sections.should_full_index(form, token_count).
    """
    section_nodes = [
        SectionNode(
            label=s.label,
            title=s.title,
            text=s.text,
            summary="",
            summary_data={},
            chunks=[],
        )
        for s in sections
    ]
    return FilingTree(
        metadata=metadata,
        sections=section_nodes,
        indexed_at=datetime.now(UTC),
        indexer_model=RAW_INDEXER_MODEL,
    )


SECTION_PROMPT_TEMPLATE = (
    "You are summarizing a SEC filing section for a research database.\n"
    "Section: {label} ({form} for {ticker}, filed {filed})\n\n"
    "Be precise, neutral, and factual. Do not speculate.\n"
    "`severity` is 1 (benign) to 5 (existential / business-threatening).\n"
    "`tickers_or_entities` are tickers, company names, products, or specific "
    "named entities mentioned in the text.\n\n"
    "Return JSON matching the schema exactly.\n\n"
    "--- TEXT ---\n{text}\n--- END ---"
)

SYNTHESIS_PROMPT_TEMPLATE = (
    "You are synthesizing chunk-level summaries of one section of a SEC filing "
    "into a single section-level summary.\n"
    "Section: {label} ({form} for {ticker}, filed {filed})\n\n"
    "Each chunk summary below already conforms to the schema. Produce a single "
    "schema'd object that captures the section's overall message, drawing key "
    "points and themes from the chunk summaries. `severity` is the maximum of "
    "the chunks unless the chunks contradict each other.\n\n"
    "--- CHUNK SUMMARIES (JSON) ---\n{chunk_summaries}\n--- END ---"
)


class TreeBuilder:
    """Builds a FilingTree from a FilingMetadata + list[Section] via zo_client.

    Caller passes in the ZoClient — that way the same client (with its token
    config) is shared across calls, and tests can inject a mock.
    """

    def __init__(
        self,
        client: ZoClient,
        *,
        model: str = DEFAULT_MODEL_INDEX,
        max_chunk_tokens: int = DEFAULT_MAX_CHUNK_TOKENS,
    ) -> None:
        self.client = client
        self.model = model
        self.max_chunk_tokens = max_chunk_tokens

    def build(self, metadata: FilingMetadata, sections: list[Section]) -> FilingTree:
        section_nodes = [self._build_section(metadata, s) for s in sections]
        return FilingTree(
            metadata=metadata,
            sections=section_nodes,
            indexed_at=datetime.now(UTC),
            indexer_model=self.model,
        )

    def _build_section(
        self, metadata: FilingMetadata, section: Section
    ) -> SectionNode:
        if _estimate_tokens(section.text) <= self.max_chunk_tokens:
            data = self._summarize_text(metadata, section.label, section.text)
            return SectionNode(
                label=section.label,
                title=section.title,
                text=section.text,
                summary=data.get("one_sentence_summary", ""),
                summary_data=data,
                chunks=[],
            )

        chunks_text = _chunk_text(section.text, target_tokens=self.max_chunk_tokens)
        chunk_nodes: list[ChunkNode] = []
        for i, ct in enumerate(chunks_text):
            data = self._summarize_text(metadata, f"{section.label}/chunk{i}", ct)
            chunk_nodes.append(
                ChunkNode(
                    chunk_index=i,
                    text=ct,
                    summary=data.get("one_sentence_summary", ""),
                    summary_data=data,
                )
            )

        synth_data = self._synthesize_section(metadata, section.label, chunk_nodes)
        return SectionNode(
            label=section.label,
            title=section.title,
            text=section.text,
            summary=synth_data.get("one_sentence_summary", ""),
            summary_data=synth_data,
            chunks=chunk_nodes,
        )

    def _summarize_text(
        self, metadata: FilingMetadata, label: str, text: str
    ) -> dict[str, Any]:
        prompt = SECTION_PROMPT_TEMPLATE.format(
            label=label,
            form=metadata.form,
            ticker=metadata.ticker,
            filed=metadata.filed.isoformat(),
            text=text,
        )
        return self._ask(prompt)

    def _synthesize_section(
        self, metadata: FilingMetadata, label: str, chunks: list[ChunkNode]
    ) -> dict[str, Any]:
        import json
        chunk_dump = json.dumps([c.summary_data for c in chunks], indent=2)
        prompt = SYNTHESIS_PROMPT_TEMPLATE.format(
            label=label,
            form=metadata.form,
            ticker=metadata.ticker,
            filed=metadata.filed.isoformat(),
            chunk_summaries=chunk_dump,
        )
        return self._ask(prompt)

    def _ask(self, prompt: str) -> dict[str, Any]:
        result = self.client.ask(
            input=prompt,
            model=self.model,
            output_format=schemas.SECTION_SUMMARY_SCHEMA,
            repair=schemas.SECTION_SUMMARY_REPAIR,
        )
        # We always return data, even on failure — the schema repair fills
        # defaults so downstream code never sees a missing key. Failures show
        # up as empty strings / lists; the indexer can surface this in logs.
        if not result.ok and not result.data:
            return _empty_summary()
        return result.data if isinstance(result.data, dict) else _empty_summary()


def _empty_summary() -> dict[str, Any]:
    return {
        "one_sentence_summary": "",
        "key_points": [],
        "themes": [],
        "severity": 0,
        "tickers_or_entities": [],
    }


def _estimate_tokens(text: str) -> int:
    """Rough char-to-token estimate. ~4 chars/token is a common heuristic."""
    return len(text) // 4


def _chunk_text(text: str, *, target_tokens: int) -> list[str]:
    """Greedy paragraph-fill chunker. Splits on blank lines first.

    If a single paragraph alone exceeds the budget, we split it on sentence
    boundaries as a fallback — rare but happens with long unbroken regulatory
    prose.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for p in paragraphs:
        p_tokens = _estimate_tokens(p)
        if p_tokens > target_tokens:
            # Flush whatever we have, then split this oversize paragraph.
            if current:
                chunks.append("\n\n".join(current))
                current, current_tokens = [], 0
            chunks.extend(_split_long_paragraph(p, target_tokens=target_tokens))
            continue
        if current_tokens + p_tokens > target_tokens and current:
            chunks.append("\n\n".join(current))
            current = [p]
            current_tokens = p_tokens
        else:
            current.append(p)
            current_tokens += p_tokens
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _split_long_paragraph(p: str, *, target_tokens: int) -> list[str]:
    """Split a single oversize paragraph on sentence boundaries."""
    # Naive sentence split — periods followed by space and capital. Good enough.
    import re

    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", p)
    out: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for s in sentences:
        s_tokens = _estimate_tokens(s)
        if current_tokens + s_tokens > target_tokens and current:
            out.append(" ".join(current))
            current = [s]
            current_tokens = s_tokens
        else:
            current.append(s)
            current_tokens += s_tokens
    if current:
        out.append(" ".join(current))
    return out


# Re-export `time` so callers can monkeypatch sleep/jitter if we add backoff later.
_TIME = time
