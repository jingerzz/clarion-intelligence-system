"""Two-stage search over indexed filings.

Stage 1 — keyword: tokenize the query, score every section/chunk by keyword
frequency (themes weighted 2x), return top-k hits. Fast baseline.

Stage 2 — LLM reasoning: when the top keyword score is below
`reasoning_threshold` (3.0 by default, matching Clarion's value), call /zo/ask
with a condensed catalog of indexed sections (path + title + summary). The
model returns relevant section paths; those become additional SearchHits
merged with the keyword results.

Stage 2 only runs when:
- `reasoning=True` (default) AND
- the keyword stage produced a top score below `reasoning_threshold`, AND
- a ZoClient is available (passed in or constructed from env). If no client
  is available — typically because the user hasn't set ZO_API_KEY and isn't
  inside a chat agent turn — Stage 2 is silently skipped.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ai_buffett_zo.llm import Repair, ZoAuthError, ZoClient
from ai_buffett_zo.secrag.storage import list_indexed, load_tree
from ai_buffett_zo.secrag.tree import ChunkNode, FilingTree, SectionNode

logger = logging.getLogger(__name__)

# Common English stopwords. Not exhaustive — just enough to keep "what is the
# risk for nvda" from matching every doc.
STOPWORDS: frozenset[str] = frozenset(
    ["a", "an", "the", "and", "or", "but", "if", "then", "so", "as", "at", "by", "for", "from", "in", "into", "of", "on", "to", "with", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did", "this", "that", "these", "those", "it", "its", "which", "who", "whom", "what", "when", "where", "why", "how", "about", "against"]
)

WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]*")
SNIPPET_CONTEXT_CHARS = 240  # how much surrounding text to include with a hit

# When the top keyword hit's score is below this threshold AND a client is
# available, escalate to LLM-driven tree navigation. Matches the value in
# Clarion sec-rag's tree_search.
DEFAULT_REASONING_THRESHOLD: float = 3.0

# Score assigned to LLM-selected hits in the merged result. Below the
# typical threshold for keyword "strong" hits but above near-zero noise.
LLM_HIT_SCORE: float = 2.0

# Hard cap on per-section summary length sent to /zo/ask. Keeps the catalog
# size manageable even with hundreds of indexed filings.
_CATALOG_SUMMARY_CHARS: int = 220


@dataclass(frozen=True)
class SearchHit:
    """One result from a search.

    score: keyword frequency score (higher is better; not normalized).
    snippet: short excerpt of `text` around the first matched keyword.
    citation: human-readable, e.g. "NVDA 10-K filed 2026-02-21 → risk_factors".
    path: e.g. "risk_factors" or "risk_factors/chunk2"

    is_pointer_only + pointer_target: True when the hit came from a section
    that incorporates substantive content by reference (Items 10-14 → DEF 14A,
    Items 7-8 → Annual Report). Callers (e.g. the eval skill) can surface
    "this section is a pointer; substantive content lives in [target]" instead
    of treating the snippet as fact.
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
    is_pointer_only: bool = False
    pointer_target: str | None = None


def search(
    query: str,
    *,
    root: Path,
    tickers: Iterable[str] | None = None,
    top_k: int = 10,
    section_labels: Iterable[str] | None = None,
    reasoning: bool = True,
    reasoning_threshold: float = DEFAULT_REASONING_THRESHOLD,
    client: ZoClient | None = None,
) -> list[SearchHit]:
    """Two-stage search: keyword first; escalate to LLM when keyword is weak.

    Args:
        query: free-form query string
        root: indexed corpus root (`~/clarion/sec/`)
        tickers: optional ticker scope (case-insensitive)
        top_k: max results to return
        section_labels: optional section-label filter (e.g., ["risk_factors"])
        reasoning: if True (default), run Stage 2 LLM reasoning when the top
            keyword score is below `reasoning_threshold` and a client is
            available
        reasoning_threshold: top keyword score below which Stage 2 fires
        client: optional pre-built ZoClient. If None and reasoning is enabled,
            we try to construct one from env (ZO_API_KEY or
            ZO_CLIENT_IDENTITY_TOKEN). If neither is set, Stage 2 is silently
            skipped — keyword results are returned alone.
    """
    terms = _tokenize(query)
    if not terms:
        return []

    ticker_filter = {t.upper() for t in tickers} if tickers else None
    label_filter = set(section_labels) if section_labels else None

    keyword_hits = _keyword_search(
        terms,
        root=root,
        ticker_filter=ticker_filter,
        label_filter=label_filter,
    )

    if not reasoning:
        return _sorted_top_k(keyword_hits, top_k)

    top_score = keyword_hits[0].score if keyword_hits else 0.0
    if top_score >= reasoning_threshold:
        return _sorted_top_k(keyword_hits, top_k)

    # Stage 2: LLM reasoning over the catalog
    resolved_client = client or _try_build_client()
    if resolved_client is None:
        return _sorted_top_k(keyword_hits, top_k)

    llm_hits = _llm_reason_search(
        query=query,
        client=resolved_client,
        root=root,
        ticker_filter=ticker_filter,
        label_filter=label_filter,
    )

    seen = {(h.ticker, h.accession, h.path) for h in keyword_hits}
    merged = list(keyword_hits) + [
        h for h in llm_hits if (h.ticker, h.accession, h.path) not in seen
    ]
    return _sorted_top_k(merged, top_k)


def _keyword_search(
    terms: set[str],
    *,
    root: Path,
    ticker_filter: set[str] | None,
    label_filter: set[str] | None,
) -> list[SearchHit]:
    """Stage 1: keyword scoring (extracted from the original search())."""
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
    return hits


def _sorted_top_k(hits: list[SearchHit], top_k: int) -> list[SearchHit]:
    return sorted(hits, key=lambda h: h.score, reverse=True)[:top_k]


def _try_build_client() -> ZoClient | None:
    """Construct a ZoClient from env if possible. None on auth failure."""
    try:
        client = ZoClient()
        client._token()  # force token resolution to fail fast if absent
        return client
    except ZoAuthError:
        return None
    except Exception:  # noqa: BLE001
        return None


# ---- Stage 2: LLM reasoning over the indexed catalog ----------------------


_REASONING_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "selected_paths": {
            "type": "array",
            "items": {"type": "string"},
        },
        "rationale": {"type": "string"},
    },
    "required": ["selected_paths"],
}

_REASONING_REPAIR = Repair(
    aliases={
        "paths": "selected_paths",
        "selected": "selected_paths",
        "results": "selected_paths",
        "reason": "rationale",
        "explanation": "rationale",
    },
    defaults={
        "selected_paths": [],
        "rationale": "",
    },
)

_REASONING_PROMPT_TEMPLATE = (
    "You are an investment-research librarian. The user asked:\n\n"
    "  {query}\n\n"
    "Below is a catalog of indexed SEC filing sections. Each line is "
    "`TICKER/ACCESSION/SECTION_PATH: TITLE — SUMMARY`. Select the section paths "
    "MOST LIKELY to contain information that answers the user's question. "
    "Return up to {max_results} paths, each as a string in the exact format "
    "`TICKER/ACCESSION/SECTION_PATH` from the catalog. Be selective — empty list "
    "is preferable to irrelevant guesses.\n\n"
    "--- CATALOG ---\n{catalog}\n--- END ---\n"
)


def _llm_reason_search(
    *,
    query: str,
    client: ZoClient,
    root: Path,
    ticker_filter: set[str] | None,
    label_filter: set[str] | None,
    max_results: int = 10,
) -> list[SearchHit]:
    """Stage 2: ask /zo/ask which catalog entries are relevant; load + return."""
    catalog_lines, path_index = _build_catalog(
        root, ticker_filter=ticker_filter, label_filter=label_filter
    )
    if not catalog_lines:
        return []
    catalog = "\n".join(catalog_lines)
    prompt = _REASONING_PROMPT_TEMPLATE.format(
        query=query, max_results=max_results, catalog=catalog
    )

    result = client.ask(
        input=prompt,
        output_format=_REASONING_SCHEMA,
        repair=_REASONING_REPAIR,
    )
    if not result.ok or not isinstance(result.data, dict):
        logger.warning("LLM reasoning step failed: %s", result.error or result.problems)
        return []

    selected: list[str] = result.data.get("selected_paths") or []
    out: list[SearchHit] = []
    for raw_path in selected:
        if not isinstance(raw_path, str):
            continue
        entry = path_index.get(raw_path.strip())
        if entry is None:
            continue
        tree, section, chunk = entry
        out.append(_hit_from_entry(tree, section, chunk, score=LLM_HIT_SCORE))
    return out


def _build_catalog(
    root: Path,
    *,
    ticker_filter: set[str] | None,
    label_filter: set[str] | None,
) -> tuple[list[str], dict[str, tuple[FilingTree, SectionNode, ChunkNode | None]]]:
    """Return (catalog_lines, path_index) where path_index maps the catalog's
    string paths back to the underlying objects."""
    lines: list[str] = []
    index: dict[str, tuple[FilingTree, SectionNode, ChunkNode | None]] = {}
    for meta in list_indexed(root, ticker=None):
        if ticker_filter and meta.ticker not in ticker_filter:
            continue
        try:
            tree = load_tree(root, meta.ticker, meta.accession)
        except (FileNotFoundError, ValueError):
            continue
        for section in tree.sections:
            if label_filter and section.label not in label_filter:
                continue
            if section.chunks:
                for chunk in section.chunks:
                    path = f"{meta.ticker}/{meta.accession}/{section.label}/chunk{chunk.chunk_index}"
                    summary = (chunk.summary or "")[:_CATALOG_SUMMARY_CHARS]
                    lines.append(f"{path}: {section.title} — {summary}")
                    index[path] = (tree, section, chunk)
            else:
                path = f"{meta.ticker}/{meta.accession}/{section.label}"
                summary = (section.summary or "")[:_CATALOG_SUMMARY_CHARS]
                lines.append(f"{path}: {section.title} — {summary}")
                index[path] = (tree, section, None)
    return lines, index


def _hit_from_entry(
    tree: FilingTree,
    section: SectionNode,
    chunk: ChunkNode | None,
    *,
    score: float,
) -> SearchHit:
    """Build a SearchHit from a (tree, section, chunk?) tuple — no keyword math."""
    meta = tree.metadata
    text = chunk.text if chunk is not None else section.text
    snippet = _shorten(text, SNIPPET_CONTEXT_CHARS)
    path = (
        f"{section.label}/chunk{chunk.chunk_index}"
        if chunk is not None
        else section.label
    )
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
        is_pointer_only=section.is_pointer_only,
        pointer_target=section.pointer_target,
    )


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
        is_pointer_only=section.is_pointer_only,
        pointer_target=section.pointer_target,
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
        is_pointer_only=section.is_pointer_only,
        pointer_target=section.pointer_target,
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
