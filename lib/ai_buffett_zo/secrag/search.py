"""Keyword search over indexed filings.

v1 is intentionally simple: tokenize the query, score every section/chunk by
keyword frequency, return top-k hits with citations. No embeddings, no LLM
tree-navigation.

The search corpus is whatever's indexed under `root`. Filter by `tickers` to
scope a query.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ai_buffett_zo.secrag.storage import list_indexed, load_tree
from ai_buffett_zo.secrag.tree import ChunkNode, FilingTree, SectionNode

# Common English stopwords. Not exhaustive — just enough to keep "what is the
# risk for nvda" from matching every doc.
STOPWORDS: frozenset[str] = frozenset(
    ["a", "an", "the", "and", "or", "but", "if", "then", "so", "as", "at", "by", "for", "from", "in", "into", "of", "on", "to", "with", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did", "this", "that", "these", "those", "it", "its", "which", "who", "whom", "what", "when", "where", "why", "how", "about", "against"]
)

WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]*")
SNIPPET_CONTEXT_CHARS = 240  # how much surrounding text to include with a hit


@dataclass(frozen=True)
class SearchHit:
    """One result from a search.

    score: keyword frequency score (higher is better; not normalized).
    snippet: short excerpt of `text` around the first matched keyword.
    citation: human-readable, e.g. "NVDA 10-K filed 2026-02-21 → risk_factors".
    path: e.g. "risk_factors" or "risk_factors/chunk2"
    """

    ticker: str
    accession: str
    form: str
    filed: str
    section_label: str
    section_title: str
    path: str
    snippet: str
    score: float
    citation: str


def search(
    query: str,
    *,
    root: Path,
    tickers: Iterable[str] | None = None,
    top_k: int = 10,
    section_labels: Iterable[str] | None = None,
) -> list[SearchHit]:
    """Score every leaf node against the query; return the top_k hits.

    Leaves are: chunked sections' chunks (when present), or whole sections
    (when no chunks). We never score both — would double-count.
    """
    terms = _tokenize(query)
    if not terms:
        return []

    ticker_filter = {t.upper() for t in tickers} if tickers else None
    label_filter = set(section_labels) if section_labels else None

    hits: list[SearchHit] = []
    for meta in list_indexed(root, ticker=None):
        if ticker_filter and meta.ticker not in ticker_filter:
            continue
        try:
            tree = load_tree(root, meta.ticker, meta.accession)
        except (FileNotFoundError, ValueError):
            continue
        hits.extend(_score_tree(tree, terms, label_filter=label_filter))

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:top_k]


def _score_tree(
    tree: FilingTree,
    terms: set[str],
    *,
    label_filter: set[str] | None,
) -> list[SearchHit]:
    out: list[SearchHit] = []
    for section in tree.sections:
        if label_filter and section.label not in label_filter:
            continue
        if section.chunks:
            for chunk in section.chunks:
                hit = _score_chunk(tree, section, chunk, terms)
                if hit is not None:
                    out.append(hit)
        else:
            hit = _score_section(tree, section, terms)
            if hit is not None:
                out.append(hit)
    return out


def _score_section(
    tree: FilingTree, section: SectionNode, terms: set[str]
) -> SearchHit | None:
    score, position = _score_text(_searchable_text(section), terms)
    if score == 0:
        return None
    snippet = _snippet(section.text, terms, around=position)
    meta = tree.metadata
    return SearchHit(
        ticker=meta.ticker,
        accession=meta.accession,
        form=meta.form,
        filed=meta.filed.isoformat(),
        section_label=section.label,
        section_title=section.title,
        path=section.label,
        snippet=snippet,
        score=score,
        citation=_citation(meta.ticker, meta.form, meta.filed.isoformat(), section.label),
    )


def _score_chunk(
    tree: FilingTree,
    section: SectionNode,
    chunk: ChunkNode,
    terms: set[str],
) -> SearchHit | None:
    haystack = _searchable_chunk(section, chunk)
    score, position = _score_text(haystack, terms)
    if score == 0:
        return None
    snippet = _snippet(chunk.text, terms, around=position)
    meta = tree.metadata
    path = f"{section.label}/chunk{chunk.chunk_index}"
    return SearchHit(
        ticker=meta.ticker,
        accession=meta.accession,
        form=meta.form,
        filed=meta.filed.isoformat(),
        section_label=section.label,
        section_title=section.title,
        path=path,
        snippet=snippet,
        score=score,
        citation=_citation(meta.ticker, meta.form, meta.filed.isoformat(), path),
    )


def _searchable_text(section: SectionNode) -> str:
    """Section-level searchable string. Includes title, summary, themes, body.

    Themes are weighted more heavily by being inserted twice — they're the
    indexer's distillation of what the section is about.
    """
    themes = section.summary_data.get("themes", []) if section.summary_data else []
    pieces = [
        section.title,
        section.summary,
        " ".join(themes) if themes else "",
        " ".join(themes) if themes else "",  # double-weight
        section.text,
    ]
    return "\n".join(p for p in pieces if p)


def _searchable_chunk(section: SectionNode, chunk: ChunkNode) -> str:
    themes = chunk.summary_data.get("themes", []) if chunk.summary_data else []
    pieces = [
        section.title,
        chunk.summary,
        " ".join(themes) if themes else "",
        " ".join(themes) if themes else "",
        chunk.text,
    ]
    return "\n".join(p for p in pieces if p)


def _score_text(haystack: str, terms: set[str]) -> tuple[float, int]:
    """Frequency score + offset of the first matching term in `haystack`."""
    haystack_lower = haystack.lower()
    score = 0.0
    first_pos = -1
    for term in terms:
        # \b-bounded matches to avoid partial hits ("AI" inside "GAINING").
        for m in re.finditer(rf"\b{re.escape(term)}\b", haystack_lower):
            score += 1.0
            if first_pos == -1:
                first_pos = m.start()
    return score, first_pos


def _snippet(text: str, terms: set[str], *, around: int) -> str:
    """Excerpt of ~SNIPPET_CONTEXT_CHARS centered on `around`."""
    if around < 0:
        return _shorten(text, SNIPPET_CONTEXT_CHARS)
    half = SNIPPET_CONTEXT_CHARS // 2
    start = max(0, around - half)
    end = min(len(text), around + half)
    out = text[start:end].strip()
    if start > 0:
        out = "…" + out
    if end < len(text):
        out = out + "…"
    return out


def _shorten(text: str, n: int) -> str:
    return text[:n] + "…" if len(text) > n else text


def _tokenize(query: str) -> set[str]:
    return {
        m.group(0).lower()
        for m in WORD_RE.finditer(query)
        if m.group(0).lower() not in STOPWORDS and len(m.group(0)) > 1
    }


def _citation(ticker: str, form: str, filed: str, path: str) -> str:
    return f"{ticker} {form} filed {filed} → {path}"
