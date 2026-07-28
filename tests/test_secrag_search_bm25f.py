"""Tests for the BM25F stage-1 scorer, doc2query field, stemming, phrase
bonus, structural promotion, and RRF fusion (issue: retrieval upgrade)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from ai_buffett_zo.llm import AskResult
from ai_buffett_zo.secrag import (
    ChunkNode,
    FilingMetadata,
    FilingTree,
    SectionNode,
    save_tree,
    search,
)
from ai_buffett_zo.secrag.search import (
    SearchHit,
    _rrf_fuse,
    _stem,
    _tokenize,
    _tokenize_list,
)


def _meta(ticker: str, form: str = "10-K", filed: date = date(2026, 2, 21)) -> FilingMetadata:
    return FilingMetadata(
        cik="0000000000",
        ticker=ticker,
        company=f"{ticker} Inc.",
        form=form,
        filed=filed,
        period=filed,
        accession=f"acc-{ticker}-{filed.isoformat()}",
        primary_doc="doc.htm",
        primary_doc_url=f"https://example/{ticker}.htm",
    )


def _section(
    label: str,
    title: str,
    text: str,
    *,
    summary: str = "",
    themes: list[str] | None = None,
    questions: list[str] | None = None,
    chunks: list[ChunkNode] | None = None,
) -> SectionNode:
    return SectionNode(
        label=label,
        title=title,
        text=text,
        summary=summary,
        summary_data={
            "themes": themes or [],
            "retrieval_questions": questions or [],
        },
        chunks=chunks or [],
    )


def _filing(
    ticker: str,
    sections: list[SectionNode],
    *,
    form: str = "10-K",
    filed: date = date(2026, 2, 21),
) -> FilingTree:
    return FilingTree(
        metadata=_meta(ticker, form, filed),
        sections=sections,
        indexed_at=datetime(2026, 7, 28, tzinfo=UTC),
        indexer_model="test",
    )


# ---- Stemming ---------------------------------------------------------------


def test_stem_strips_common_suffixes() -> None:
    assert _stem("risks") == "risk"
    assert _stem("factors") == "factor"
    assert _stem("reported") == "report"
    assert _stem("operating") == "operat"


def test_stem_leaves_short_words_alone() -> None:
    assert _stem("risk") == "risk"
    assert _stem("cash") == "cash"


def test_query_matches_plural_in_text(tmp_path: Path) -> None:
    """Stemming bridges singular/plural between query and filing text."""
    save_tree(
        tmp_path,
        _filing(
            "NVDA",
            [_section("risk_factors", "Item 1A", "There are several key risks facing us.")],
        ),
    )
    hits = search("risk", root=tmp_path, reasoning=False)
    assert len(hits) == 1
    assert "risks" in hits[0].snippet


# ---- IDF discounts common terms --------------------------------------------


def test_idf_rare_term_beats_common_term(tmp_path: Path) -> None:
    """A section matching the RARE query term outranks one matching only the
    term every document contains."""
    for i, ticker in enumerate(["AAA", "BBB", "CCC", "DDD"]):
        text = "revenue grew this year."
        if ticker == "AAA":
            text = "revenue grew. datacenter buildout accelerated."
        save_tree(
            tmp_path,
            _filing(ticker, [_section("mdna", "Item 7", text)], filed=date(2026, 1, i + 1)),
        )
    hits = search("datacenter revenue", root=tmp_path, reasoning=False)
    assert hits[0].ticker == "AAA"


# ---- doc2query questions field ---------------------------------------------


def test_questions_field_bridges_vocabulary_gap(tmp_path: Path) -> None:
    """A node whose doc2query questions match the query outranks a node with
    the same body text but no questions."""
    save_tree(
        tmp_path,
        _filing(
            "AAA",
            [
                _section(
                    "mdna",
                    "Item 7",
                    "Cash generated was substantial this period.",
                    questions=["How much liquidity does the company have?"],
                ),
            ],
            filed=date(2026, 1, 1),
        ),
    )
    save_tree(
        tmp_path,
        _filing(
            "BBB",
            [
                _section(
                    "mdna",
                    "Item 7",
                    "Cash generated was substantial this period. liquidity",
                ),
            ],
            filed=date(2026, 1, 2),
        ),
    )
    hits = search("liquidity", root=tmp_path, reasoning=False)
    scores = {h.ticker: h.score for h in hits}
    assert scores["AAA"] > scores["BBB"]


def test_indexes_without_questions_still_search(tmp_path: Path) -> None:
    """Pre-doc2query indexes (no retrieval_questions key) work unchanged."""
    section = SectionNode(
        label="business",
        title="Item 1",
        text="We sell GPUs.",
        summary="",
        summary_data={},  # old index: no themes, no retrieval_questions
        chunks=[],
    )
    save_tree(tmp_path, _filing("NVDA", [section]))
    hits = search("GPUs", root=tmp_path, reasoning=False)
    assert len(hits) == 1


# ---- Phrase bonus -----------------------------------------------------------


def test_phrase_bonus_prefers_verbatim_phrase(tmp_path: Path) -> None:
    save_tree(
        tmp_path,
        _filing(
            "AAA",
            [_section("risk_factors", "Item 1A", "Supply chain disruption is our top risk.")],
            filed=date(2026, 1, 1),
        ),
    )
    save_tree(
        tmp_path,
        _filing(
            "BBB",
            [_section("risk_factors", "Item 1A", "The supply of chips and the chain of custody.")],
            filed=date(2026, 1, 2),
        ),
    )
    hits = search("supply chain", root=tmp_path, reasoning=False)
    scores = {h.ticker: h.score for h in hits}
    assert scores["AAA"] > scores["BBB"]


# ---- Structural promotion ---------------------------------------------------


def test_balance_sheet_query_promotes_financials(tmp_path: Path) -> None:
    """A 'balance sheet' query surfaces the curated financials section even
    when its title/text share no vocabulary with the query."""
    save_tree(
        tmp_path,
        _filing(
            "NVDA",
            [
                _section(
                    "risk_factors",
                    "Item 1A. Risk Factors",
                    "Balance of power in the sheet metal industry.",  # decoy match
                ),
                _section(
                    "financials",
                    "Item 8. Financial Statements and Supplementary Data",
                    "Consolidated totals: assets 100, liabilities 40.",
                ),
            ],
        ),
    )
    hits = search("balance sheet", root=tmp_path, reasoning=False)
    assert any(h.section_label == "financials" for h in hits)


def test_structural_promotion_respects_label_filter(tmp_path: Path) -> None:
    """An explicit section_labels filter is never widened by promotion."""
    save_tree(
        tmp_path,
        _filing(
            "NVDA",
            [
                _section("risk_factors", "Item 1A", "Balance sheet risk discussion."),
                _section("financials", "Item 8", "Assets and liabilities."),
            ],
        ),
    )
    hits = search(
        "balance sheet", root=tmp_path, reasoning=False, section_labels=["risk_factors"]
    )
    assert all(h.section_label == "risk_factors" for h in hits)


# ---- RRF fusion -------------------------------------------------------------


def _hit(ticker: str, path: str, score: float) -> SearchHit:
    return SearchHit(
        ticker=ticker,
        accession=f"acc-{ticker}",
        form="10-K",
        filed="2026-02-21",
        section_label=path.split("/")[0],
        section_title=path,
        path=path,
        snippet="",
        score=score,
        citation=f"{ticker} 10-K filed 2026-02-21 → {path}",
    )


def test_rrf_agreement_beats_single_list_rank() -> None:
    """A node ranked #2 by two signals outranks nodes ranked #1 by one each."""
    agreed = _hit("AAA", "mdna", 1.0)
    only_kw = _hit("BBB", "business", 9.0)
    only_llm = _hit("CCC", "risk_factors", 2.0)
    fused = _rrf_fuse(
        [([only_kw, agreed], 1.0), ([only_llm, agreed], 1.0)],
        k=60,
        top_k=3,
    )
    assert fused[0].path == "mdna"


def test_rrf_keeps_strongest_underlying_score() -> None:
    a1 = _hit("AAA", "mdna", 0.5)
    a2 = _hit("AAA", "mdna", 2.0)  # same node via another signal, higher score
    fused = _rrf_fuse([([a1], 1.0), ([a2], 1.0)], k=60, top_k=5)
    assert len(fused) == 1
    assert fused[0].score == 2.0


def test_rrf_zero_weight_lists_ignored() -> None:
    a = _hit("AAA", "mdna", 1.0)
    b = _hit("BBB", "business", 1.0)
    fused = _rrf_fuse([([a], 1.0), ([b], 0.0)], k=60, top_k=5)
    assert [h.ticker for h in fused] == ["AAA"]


# ---- Query rewrite (weak path) ---------------------------------------------


class RewriteFakeClient:
    """Fake ZoClient scripting BOTH weak-path calls: rewrite + reasoning."""

    def __init__(self, paraphrases: list[str]) -> None:
        self.paraphrases = paraphrases
        self.prompts: list[str] = []

    def _token(self) -> str:
        return "zo_sk_fake"

    def ask(self, *, input=None, output_format=None, repair=None, **kwargs) -> AskResult:  # noqa: A002
        self.prompts.append(input or "")
        props = (output_format or {}).get("properties", {})
        if "paraphrases" in props:
            data = {"paraphrases": self.paraphrases}
        else:
            data = {"selected_paths": [], "rationale": ""}
        return AskResult(ok=True, data=data, raw=data, elapsed_s=0.01, model="zo:test")


def test_rewrite_paraphrase_hits_surface_in_results(tmp_path: Path) -> None:
    """A doc only findable via the paraphrase's vocabulary is still returned."""
    save_tree(
        tmp_path,
        _filing(
            "NVDA",
            [_section("mdna", "Item 7", "Liquidity remained strong across the period.")],
        ),
    )
    client = RewriteFakeClient(paraphrases=["liquidity position"])
    hits = search("how much cash cushion", root=tmp_path, client=client)
    assert any(h.section_label == "mdna" for h in hits)
    assert len(client.prompts) == 2  # rewrite + reasoning


def test_rewrite_disabled_via_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLARION_QUERY_REWRITE", "0")
    save_tree(
        tmp_path,
        _filing("NVDA", [_section("mdna", "Item 7", "Liquidity remained strong.")]),
    )
    client = RewriteFakeClient(paraphrases=["liquidity position"])
    search("how much cash cushion", root=tmp_path, client=client)
    # Only the reasoning call — no rewrite call.
    assert len(client.prompts) == 1
    assert "CATALOG" in client.prompts[0]
