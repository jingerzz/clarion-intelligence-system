"""Two-stage search over indexed filings.

Stage 1 — BM25F keyword: tokenize the query (stop-words dropped, light
suffix-stemming), score every section/chunk with field-weighted BM25
(title 5 / questions 4 / summary+themes 3 / text 1), IDF computed over the
searched corpus slice, per-field length normalization, plus a verbatim-phrase
bonus. `questions` is the doc2query field: hypothetical questions generated at
index time (summary_data["retrieval_questions"]); absent on older indexes,
which simply get no hits from that field.

Stage 2 — LLM reasoning: when the top BM25F score is below
`reasoning_threshold`, call /zo/ask with a condensed catalog of indexed
sections (path + title + summary). The model returns relevant section paths;
those become additional SearchHits.

Weak-query path extras (both config-gated, both require a client):
- Query rewriting: the LLM paraphrases the query into ≤N alternate phrasings;
  each is re-scored with BM25F. Gated by CLARION_QUERY_REWRITE (default on).
- Reciprocal Rank Fusion: the original ranking, paraphrase rankings, LLM
  reasoning picks, and any structural-intent target are merged by rank
  position (RRF, k=60). Nodes surfaced by multiple signals rise to the top
  regardless of any single signal's score scale. Result ORDER is the fused
  rank; each hit's `score` still carries its strongest underlying signal
  score (BM25F, or LLM_HIT_SCORE for reasoning-only picks) — do not re-sort
  fused results by `score`.

SEC-aware structural promotion: queries that clearly target the financial
statements ("balance sheet", "cash flow statement", "capex"…) promote the
curated `financials` section into the results even when vocabulary alone
misses it (its title is generic — "Item 8. Financial Statements…").

Stage 2 (and the rewrite) only run when:
- `reasoning=True` (default) AND
- the BM25F stage produced a top score below `reasoning_threshold`, AND
- a ZoClient is available (passed in or constructed from env). If no client
  is available — typically because the user hasn't set ZO_API_KEY and isn't
  inside a chat agent turn — the LLM extras are silently skipped.

NOTE on score scale: BM25F scores are corpus-size dependent (IDF grows with
the number of indexed nodes). `DEFAULT_REASONING_THRESHOLD` is calibrated for
a realistically sized corpus (dozens of filings); tiny test corpora produce
much smaller scores and should pass an explicit `reasoning_threshold`.
"""

from __future__ import annotations

import logging
import math
import os
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
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

# When the top BM25F hit's score is below this threshold AND a client is
# available, escalate to LLM-driven tree navigation (and query rewriting).
# Calibrated for a realistic corpus: a moderately rare term matching a
# weighted field (summary/title/questions) clears the bar; a common term
# matching only body text does not. Matches sec-rag's tree_search value.
DEFAULT_REASONING_THRESHOLD: float = 3.0

# Score assigned to LLM-selected hits in the merged result. Below the
# typical threshold for keyword "strong" hits but above near-zero noise.
LLM_HIT_SCORE: float = 2.0

# Hard cap on per-section summary length sent to /zo/ask. Keeps the catalog
# size manageable even with hundreds of indexed filings.
_CATALOG_SUMMARY_CHARS: int = 220

# --- BM25F parameters (standard defaults; field weights from sec-rag) -------
_BM25_K1 = 1.5
_BM25_B = 0.75
# `questions` is the doc2query field — query-shaped by construction, so when
# it matches, the match is unambiguous: above summary, below exact-title.
_FIELD_WEIGHTS: dict[str, float] = {
    "title": 5.0,
    "questions": 4.0,
    "summary": 3.0,
    "text": 1.0,
}

# --- RRF / query-rewrite parameters ------------------------------------------
_RRF_K = 60  # standard damping constant; larger flattens the rank curve
_PARAPHRASE_WEIGHT = 0.7  # paraphrases count slightly less than the original


def _query_rewrite_enabled() -> bool:
    """Config gate for LLM query rewriting (default on).

    Set CLARION_QUERY_REWRITE=0 to disable without code changes.
    """
    return os.environ.get("CLARION_QUERY_REWRITE", "1") != "0"


def _num_paraphrases() -> int:
    """How many paraphrases to request (0 disables). Clamped to [0, 5]."""
    try:
        n = int(os.environ.get("CLARION_NUM_PARAPHRASES", "3"))
    except ValueError:
        n = 3
    return max(0, min(5, n))


# --- SEC-aware structural intent ---------------------------------------------
# Queries that reference a known structural location of a 10-K/10-Q. BM25F can
# miss the right node because its title is generic ("Item 8. Financial
# Statements and Supplementary Data") while noisier siblings outrank it.
# Curated extraction gives us stable labels, so promotion is label-based.
_INTENT_PHRASES: dict[str, tuple[str, ...]] = {
    "financial_statements": (
        "cash flow statement", "statement of cash flows",
        "balance sheet", "consolidated balance sheet",
        "income statement", "statement of operations",
        "statement of stockholders equity", "statement of stockholders' equity",
        "capital expenditure", "capital expenditures", "capex",
        "ppne", "pp&e", "property, plant and equipment",
        "property plant and equipment", "net ppne", "net pp&e",
    ),
}

_INTENT_LABELS: dict[str, str] = {
    # Intent → curated section label (see sections.CURATED_SECTIONS).
    "financial_statements": "financial_statements",
}


@dataclass(frozen=True)
class SearchHit:
    """One result from a search.

    score: strongest underlying signal score for this hit (BM25F scale for
        keyword hits, LLM_HIT_SCORE for reasoning-only picks). Higher is
        better; not normalized. On the weak-query path the result ORDER is
        the RRF-fused rank, which is authoritative — don't re-sort by score.
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
    recovered_via: str | None = None


@dataclass
class _Node:
    """One searchable unit (a section, or one chunk of a chunked section)."""

    tree: FilingTree
    section: SectionNode
    chunk: ChunkNode | None
    fields: dict[str, str] = field(default_factory=dict)
    tokens: dict[str, list[str]] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.tree.metadata.ticker, self.tree.metadata.accession, self.path)

    @property
    def path(self) -> str:
        if self.chunk is not None:
            return f"{self.section.label}/chunk{self.chunk.chunk_index}"
        return self.section.label

    @property
    def raw_text(self) -> str:
        return self.chunk.text if self.chunk is not None else self.section.text


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
    """Two-stage search: BM25F first; escalate to LLM extras when weak.

    Args:
        query: free-form query string
        root: indexed corpus root (`~/clarion/sec/`)
        tickers: optional ticker scope (case-insensitive)
        top_k: max results to return
        section_labels: optional section-label filter (e.g., ["risk_factors"])
        reasoning: if True (default), run the LLM extras (tree navigation +
            query rewriting) when the top BM25F score is below
            `reasoning_threshold` and a client is available
        reasoning_threshold: top BM25F score below which the weak path fires
        client: optional pre-built ZoClient. If None and reasoning is enabled,
            we try to construct one from env (ZO_API_KEY or
            ZO_CLIENT_IDENTITY_TOKEN). If neither is set, the LLM extras are
            silently skipped — BM25F results are returned alone.
    """
    query_terms = _tokenize(query)
    if not query_terms:
        return []

    ticker_filter = {t.upper() for t in tickers} if tickers else None
    label_filter = set(section_labels) if section_labels else None

    nodes = _collect_nodes(root, ticker_filter=ticker_filter, label_filter=label_filter)
    if not nodes:
        return []

    keyword_hits = _bm25f_search(nodes, query, query_terms)
    structural_hits = _structural_hits(nodes, query, keyword_hits, label_filter)

    top_score = keyword_hits[0].score if keyword_hits else 0.0
    if not reasoning or top_score >= reasoning_threshold:
        return _with_structural(keyword_hits, structural_hits, top_k)

    # Weak-query path: bring in the LLM extras, fuse everything by rank.
    resolved_client = client or _try_build_client()
    if resolved_client is None:
        return _with_structural(keyword_hits, structural_hits, top_k)

    ranked_lists: list[tuple[list[SearchHit], float]] = [(keyword_hits, 1.0)]
    if structural_hits:
        ranked_lists.append((structural_hits, 1.0))

    if _query_rewrite_enabled():
        for paraphrase in _rewrite_query(query, resolved_client):
            p_terms = _tokenize(paraphrase)
            if not p_terms:
                continue
            p_hits = _bm25f_search(nodes, paraphrase, p_terms)
            if p_hits:
                ranked_lists.append((p_hits, _PARAPHRASE_WEIGHT))

    llm_hits = _llm_reason_search(
        query=query,
        client=resolved_client,
        root=root,
        ticker_filter=ticker_filter,
        label_filter=label_filter,
    )
    if llm_hits:
        ranked_lists.append((llm_hits, 1.0))

    return _rrf_fuse(ranked_lists, k=_RRF_K, top_k=top_k)


# ---- Stage 1: BM25F ---------------------------------------------------------


def _collect_nodes(
    root: Path,
    *,
    ticker_filter: set[str] | None,
    label_filter: set[str] | None,
) -> list[_Node]:
    """Flatten the indexed corpus slice into searchable nodes with fields.

    Sections with chunks contribute one node per chunk (not the section
    itself) so each chunk is its own hit and we don't double-count.
    """
    nodes: list[_Node] = []
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
                    nodes.append(
                        _Node(tree, section, chunk, fields=_chunk_fields(section, chunk))
                    )
            else:
                nodes.append(
                    _Node(tree, section, None, fields=_section_fields(section))
                )
    for node in nodes:
        node.tokens = {
            f: _tokenize_list(text) for f, text in node.fields.items()
        }
    return nodes


def _questions_text(summary_data: dict | None) -> str:
    """Join the doc2query questions into one searchable string.

    Absent on indexes built before doc2query — those nodes simply get no
    hits from the `questions` field.
    """
    if not summary_data:
        return ""
    questions = summary_data.get("retrieval_questions") or []
    if not isinstance(questions, list):
        return str(questions)
    return " ".join(str(q) for q in questions)


def _section_fields(section: SectionNode) -> dict[str, str]:
    """Field map for BM25F. Themes fold into the summary field — they're the
    indexer's distillation of what the section is about, and the summary
    weight (3) preserves their historical boost over body text."""
    themes = section.summary_data.get("themes", []) if section.summary_data else []
    summary_parts = [section.summary, " ".join(themes) if themes else ""]
    return {
        "title": section.title,
        "questions": _questions_text(section.summary_data),
        "summary": " ".join(p for p in summary_parts if p),
        "text": section.text,
    }


def _chunk_fields(section: SectionNode, chunk: ChunkNode) -> dict[str, str]:
    themes = chunk.summary_data.get("themes", []) if chunk.summary_data else []
    summary_parts = [chunk.summary, " ".join(themes) if themes else ""]
    return {
        "title": section.title,
        "questions": _questions_text(chunk.summary_data),
        "summary": " ".join(p for p in summary_parts if p),
        "text": chunk.text,
    }


def _bm25f_search(
    nodes: list[_Node], query: str, query_terms: set[str]
) -> list[SearchHit]:
    """Score every node with BM25F + phrase bonus; return hits sorted desc."""
    n_docs = len(nodes)
    if n_docs == 0:
        return []

    # Corpus statistics over the searched slice: document frequency per query
    # term, average token length per field.
    doc_freq: Counter[str] = Counter()
    for node in nodes:
        node_terms: set[str] = set()
        for toks in node.tokens.values():
            node_terms.update(toks)
        for term in query_terms & node_terms:
            doc_freq[term] += 1

    idf = {
        term: math.log((n_docs - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5) + 1.0)
        for term in query_terms
        if doc_freq[term] > 0
    }
    if not idf:
        return []

    avg_field_len = {
        f: (sum(len(node.tokens.get(f, [])) for node in nodes) / n_docs) or 1.0
        for f in _FIELD_WEIGHTS
    }

    hits: list[SearchHit] = []
    for node in nodes:
        score = _bm25f_score(node.tokens, idf, avg_field_len)
        score += _phrase_bonus(node.fields, query, idf, query_terms)
        if score <= 0:
            continue
        hits.append(_hit_from_node(node, score=round(score, 3), query_terms=query_terms))
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits


def _bm25f_score(
    node_tokens: dict[str, list[str]],
    idf: dict[str, float],
    avg_field_len: dict[str, float],
) -> float:
    """Field-weighted BM25 with per-field length normalization.

    Each query term contributes IDF × saturated weighted TF, where the
    weighted TF sums across fields, each length-normalized against the
    corpus average for that field.
    """
    total = 0.0
    for term, term_idf in idf.items():
        weighted_tf = 0.0
        for f, weight in _FIELD_WEIGHTS.items():
            toks = node_tokens.get(f, [])
            if not toks:
                continue
            tf = toks.count(term)
            if tf == 0:
                continue
            avgdl = avg_field_len.get(f, 1.0) or 1.0
            norm = 1.0 - _BM25_B + _BM25_B * (len(toks) / avgdl)
            weighted_tf += weight * tf / norm
        if weighted_tf > 0:
            total += term_idf * weighted_tf * (_BM25_K1 + 1) / (weighted_tf + _BM25_K1)
    return total


def _phrase_bonus(
    node_fields: dict[str, str],
    query: str,
    idf: dict[str, float],
    query_terms: set[str],
) -> float:
    """Bonus when the original query phrase (2+ words) appears verbatim in a
    field, weighted by the IDF of the rarest query term."""
    phrase = query.strip().lower()
    if len(phrase.split()) < 2 or not query_terms:
        return 0.0
    rarest = max((idf.get(t, 0.0) for t in query_terms), default=0.0)
    if rarest <= 0:
        return 0.0
    bonus = 0.0
    for f, weight in _FIELD_WEIGHTS.items():
        haystack = (node_fields.get(f) or "").lower()
        if phrase in haystack:
            bonus += 0.5 * weight * rarest
    return bonus


def _hit_from_node(
    node: _Node, *, score: float, query_terms: set[str]
) -> SearchHit:
    meta = node.tree.metadata
    return SearchHit(
        ticker=meta.ticker,
        accession=meta.accession,
        form=meta.form,
        filed=meta.filed.isoformat(),
        section_label=node.section.label,
        section_title=node.section.title,
        path=node.path,
        snippet=_snippet(node.raw_text, query_terms),
        score=score,
        citation=_citation(meta.ticker, meta.form, meta.filed.isoformat(), node.path),
        is_pointer_only=node.section.is_pointer_only,
        pointer_target=node.section.pointer_target,
        recovered_via=node.section.recovered_via,
    )


# ---- SEC-aware structural promotion -----------------------------------------


def _detect_intent(query: str) -> str | None:
    q = query.lower()
    for intent, phrases in _INTENT_PHRASES.items():
        for phrase in phrases:
            if phrase in q:
                return intent
    return None


def _structural_hits(
    nodes: list[_Node],
    query: str,
    keyword_hits: list[SearchHit],
    label_filter: set[str] | None,
) -> list[SearchHit]:
    """The curated section a structural query is really asking for, if any.

    Label-based (curated extraction gives us stable labels). No-op when the
    caller passed an explicit label filter, when intent doesn't match, or when
    the target already surfaced in the keyword results.
    """
    if label_filter:
        return []
    intent = _detect_intent(query)
    if intent is None:
        return []
    target_label = _INTENT_LABELS.get(intent)
    if target_label is None:
        return []
    if any(h.section_label == target_label for h in keyword_hits):
        return []
    # Most recent filing's target section; prefer section-level nodes.
    candidates = [n for n in nodes if n.section.label == target_label]
    if not candidates:
        return []
    candidates.sort(
        key=lambda n: (n.tree.metadata.filed, n.chunk is None), reverse=True
    )
    target = candidates[0]
    logger.info(
        "Structural promote (%s): %s %s",
        intent, target.tree.metadata.ticker, target.path,
    )
    return [_hit_from_node(target, score=0.0, query_terms=_tokenize(query))]


def _with_structural(
    keyword_hits: list[SearchHit],
    structural_hits: list[SearchHit],
    top_k: int,
) -> list[SearchHit]:
    """Easy-path merge: BM25F order wins; the structural target (if any) is
    guaranteed a slot at the bottom of top-K, never above genuine matches."""
    out = keyword_hits[:top_k]
    for extra in structural_hits:
        if any(
            (h.ticker, h.accession, h.path) == (extra.ticker, extra.accession, extra.path)
            for h in out
        ):
            continue
        if len(out) < top_k:
            out.append(extra)
        else:
            out[-1] = extra
    return out


# ---- Reciprocal Rank Fusion + query rewriting -------------------------------


def _rrf_fuse(
    ranked_lists: list[tuple[list[SearchHit], float]],
    *,
    k: int,
    top_k: int,
) -> list[SearchHit]:
    """Reciprocal Rank Fusion across ranked hit lists.

    A hit at rank r (0-indexed) in a list with weight w contributes
    w / (k + r + 1) to its node's fused score. Nodes that multiple signals
    agree on rise to the top regardless of any single signal's score scale.
    Returned hits keep their strongest underlying `score`; ORDER is fused.
    """
    fused: dict[tuple[str, str, str], float] = {}
    best: dict[tuple[str, str, str], SearchHit] = {}
    for hits, weight in ranked_lists:
        if weight <= 0 or not hits:
            continue
        for rank, hit in enumerate(hits):
            key = (hit.ticker, hit.accession, hit.path)
            fused[key] = fused.get(key, 0.0) + weight / (k + rank + 1)
            prev = best.get(key)
            if prev is None or hit.score > prev.score:
                best[key] = hit
    ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    return [best[key] for key, _ in ordered]


_REWRITE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "paraphrases": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["paraphrases"],
}

_REWRITE_REPAIR = Repair(
    aliases={
        "rewrites": "paraphrases",
        "variants": "paraphrases",
        "queries": "paraphrases",
        "alternatives": "paraphrases",
        "phrasings": "paraphrases",
    },
    defaults={"paraphrases": []},
)

_REWRITE_PROMPT_TEMPLATE = (
    "Rewrite this search query into exactly {num} alternate phrasings that "
    "preserve meaning but use different vocabulary (synonyms, plain-English "
    "rephrasings, technical terms where the original is plain). The queries "
    "search SEC filings (10-K/10-Q sections).\n\n"
    "Query: {query}"
)


def _rewrite_query(query: str, client: ZoClient) -> list[str]:
    """LLM-paraphrase a query into ≤N alternate phrasings.

    Returns paraphrases only (never the original). Empty list on failure or
    degenerate output — the caller always folds in the original query's
    results, so a bad rewrite never starves retrieval.
    """
    num = _num_paraphrases()
    if num <= 0:
        return []
    result = client.ask(
        input=_REWRITE_PROMPT_TEMPLATE.format(num=num, query=query),
        output_format=_REWRITE_SCHEMA,
        repair=_REWRITE_REPAIR,
    )
    if not result.ok or not isinstance(result.data, dict):
        logger.warning("Query rewrite failed: %s", result.error or result.problems)
        return []
    raw = result.data.get("paraphrases") or []
    cleaned: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        stripped = re.sub(r"^[\-\*•\d\.\s]+", "", item).strip()
        if stripped and stripped.lower() != query.lower() and len(stripped) < 400:
            cleaned.append(stripped)
    if cleaned:
        logger.info(
            "Query rewrite produced %d paraphrase(s) for: %.60s", len(cleaned[:num]), query
        )
    return cleaned[:num]


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
        recovered_via=section.recovered_via,
    )


# ---- Tokenization / snippets ------------------------------------------------


def _stem(word: str) -> str:
    """Lightweight suffix stripper for English plural/verb forms.

    Catches the common SEC variations: risks→risk, factors→factor,
    reported→report. Not a true stemmer; just enough to recover token overlap
    between query and filing vocabulary.
    """
    if len(word) > 4:
        for suf in ("ing", "ed", "es", "s"):
            if word.endswith(suf) and len(word) - len(suf) >= 3:
                return word[: -len(suf)]
    return word


def _tokenize(query: str) -> set[str]:
    """Unique stemmed query terms (stop-words and single chars dropped)."""
    return set(_tokenize_list(query))


def _tokenize_list(text: str) -> list[str]:
    """All stemmed tokens in order (duplicates kept — used for field TF)."""
    if not text:
        return []
    return [
        _stem(m.group(0).lower())
        for m in WORD_RE.finditer(text)
        if m.group(0).lower() not in STOPWORDS and len(m.group(0)) > 1
    ]


def _snippet(text: str, terms: set[str]) -> str:
    """Excerpt of ~SNIPPET_CONTEXT_CHARS around the first query-term match.

    Terms are stemmed, so we prefix-match (\\brisk\\w*) to find "risks" for
    stem "risk"."""
    if not text:
        return ""
    lowered = text.lower()
    first_pos = -1
    for term in terms:
        m = re.search(rf"\b{re.escape(term)}\w*", lowered)
        if m and (first_pos == -1 or m.start() < first_pos):
            first_pos = m.start()
    if first_pos == -1:
        return _shorten(text, SNIPPET_CONTEXT_CHARS)
    half = SNIPPET_CONTEXT_CHARS // 2
    start = max(0, first_pos - half)
    end = min(len(text), first_pos + half)
    out = text[start:end].strip()
    if start > 0:
        out = "…" + out
    if end < len(text):
        out = out + "…"
    return out


def _shorten(text: str, n: int) -> str:
    return text[:n] + "…" if len(text) > n else text


def _citation(ticker: str, form: str, filed: str, path: str) -> str:
    return f"{ticker} {form} filed {filed} → {path}"
