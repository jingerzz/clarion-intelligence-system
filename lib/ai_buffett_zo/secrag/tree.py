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
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from typing import Any, TypeVar

from ai_buffett_zo.llm import (
    DEFAULT_MODEL_INDEX,
    ZoClient,
    schemas,
)
from ai_buffett_zo.secrag.loader import FilingMetadata
from ai_buffett_zo.secrag.sections import Section

DEFAULT_MAX_CHUNK_TOKENS = 4000  # well under any model's context; ~16k chars
RAW_INDEX_TOKEN_LIMIT = 15_000   # safety net: a "raw" filing this long gets full indexing

# Bounded parallelism for LLM summary calls (issue #48). tree-build is ~97% of
# indexing time, and it's dominated by serial /zo/ask calls — one per section,
# plus one per chunk for long sections. The calls are independent, so running a
# handful concurrently cuts per-filing wall-clock several-fold. Kept modest to
# stay well under Zo API rate limits; the indexer still processes one filing at
# a time, so total in-flight calls are bounded by this number. Override per
# deployment via CLARION_INDEX_CONCURRENCY (read in indexer/main.py); set to 1
# to fall back to fully serial behavior.
DEFAULT_TREE_CONCURRENCY = 4

_T = TypeVar("_T")


@dataclass
class ChunkNode:
    """A piece of a section that was too big to summarize whole."""

    chunk_index: int
    text: str
    summary: str
    summary_data: dict[str, Any]


@dataclass
class SectionNode:
    """One curated section. `chunks` is empty when section fit under the budget.

    `is_pointer_only` + `pointer_target` carry forward from the source
    `Section` so downstream consumers (search results, follow-up fixes) can
    tell whether the section's text is substantive or a pointer to content
    living elsewhere.
    """

    label: str
    title: str
    text: str
    summary: str
    summary_data: dict[str, Any]
    chunks: list[ChunkNode] = field(default_factory=list)
    is_pointer_only: bool = False
    pointer_target: str | None = None
    recovered_via: str | None = None


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
            is_pointer_only=s.is_pointer_only,
            pointer_target=s.pointer_target,
            recovered_via=s.recovered_via,
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
        max_concurrency: int = DEFAULT_TREE_CONCURRENCY,
    ) -> None:
        self.client = client
        self.model = model
        self.max_chunk_tokens = max_chunk_tokens
        self.max_concurrency = max(1, max_concurrency)

    def build(self, metadata: FilingMetadata, sections: list[Section]) -> FilingTree:
        """Build a FilingTree, summarizing leaf calls with bounded parallelism.

        The work is two waves of independent LLM calls (issue #48):

        - **Phase 1 — leaves:** one summary per whole short section, plus one
          per chunk for every long section. All independent → run concurrently.
        - **Phase 2 — synthesis:** one call per long section, folding its chunk
          summaries into a section summary. Independent across sections → also
          concurrent, but depends on Phase 1 for that section's chunks.

        Output is identical to a serial build — same prompts, same model, same
        assembly order. Only the wall-clock differs. With ``max_concurrency=1``
        this degrades to fully serial execution.
        """
        # Plan: for each section, None == fits whole; else the list of chunk texts.
        plans: list[tuple[Section, list[str] | None]] = [
            (s, self._chunks_for(s)) for s in sections
        ]

        # Phase 1 — every leaf summary, in original (section, chunk) order.
        leaf_keys: list[tuple[int, int]] = []   # (section_idx, chunk_idx); -1 == whole
        leaf_fns: list[Callable[[], dict[str, Any]]] = []
        for si, (s, chunks_text) in enumerate(plans):
            if chunks_text is None:
                leaf_keys.append((si, -1))
                leaf_fns.append(partial(self._summarize_text, metadata, s.label, s.text))
            else:
                for ci, ct in enumerate(chunks_text):
                    leaf_keys.append((si, ci))
                    leaf_fns.append(
                        partial(self._summarize_text, metadata, f"{s.label}/chunk{ci}", ct)
                    )
        leaf_data = dict(zip(leaf_keys, self._map_parallel(leaf_fns), strict=True))

        # Reconstruct chunk nodes per section (in chunk order) for synthesis.
        chunk_nodes_by_section: dict[int, list[ChunkNode]] = {}
        for si, (_s, chunks_text) in enumerate(plans):
            if chunks_text is None:
                continue
            chunk_nodes_by_section[si] = [
                ChunkNode(
                    chunk_index=ci,
                    text=ct,
                    summary=leaf_data[(si, ci)].get("one_sentence_summary", ""),
                    summary_data=leaf_data[(si, ci)],
                )
                for ci, ct in enumerate(chunks_text)
            ]

        # Phase 2 — synthesis per chunked section.
        synth_idx = list(chunk_nodes_by_section.keys())
        synth_fns = [
            partial(
                self._synthesize_section, metadata, plans[si][0].label,
                chunk_nodes_by_section[si],
            )
            for si in synth_idx
        ]
        synth_data = dict(zip(synth_idx, self._map_parallel(synth_fns), strict=True))

        # Assemble section nodes in original order.
        section_nodes: list[SectionNode] = []
        for si, (s, chunks_text) in enumerate(plans):
            if chunks_text is None:
                data = leaf_data[(si, -1)]
                chunks: list[ChunkNode] = []
            else:
                data = synth_data[si]
                chunks = chunk_nodes_by_section[si]
            section_nodes.append(
                SectionNode(
                    label=s.label,
                    title=s.title,
                    text=s.text,
                    summary=data.get("one_sentence_summary", ""),
                    summary_data=data,
                    chunks=chunks,
                    is_pointer_only=s.is_pointer_only,
                    pointer_target=s.pointer_target,
                    recovered_via=s.recovered_via,
                )
            )
        return FilingTree(
            metadata=metadata,
            sections=section_nodes,
            indexed_at=datetime.now(UTC),
            indexer_model=self.model,
        )

    def _chunks_for(self, section: Section) -> list[str] | None:
        """Chunk plan for a section: None if it fits whole, else the chunk texts."""
        if _estimate_tokens(section.text) <= self.max_chunk_tokens:
            return None
        return _chunk_text(section.text, target_tokens=self.max_chunk_tokens)

    def _map_parallel(self, fns: list[Callable[[], _T]]) -> list[_T]:
        """Run zero-arg callables, returning results in input order.

        Bounded by ``max_concurrency``. Falls back to a plain serial loop when
        concurrency is 1 or there's at most one task — avoids spinning up a
        thread pool for the common short-filing case. ``ThreadPoolExecutor.map``
        preserves input order and only keeps ``max_workers`` calls in flight.
        """
        if self.max_concurrency <= 1 or len(fns) <= 1:
            return [fn() for fn in fns]
        workers = min(self.max_concurrency, len(fns))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(lambda fn: fn(), fns))

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
