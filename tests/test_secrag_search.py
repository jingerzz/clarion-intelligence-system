"""Tests for ai_buffett_zo.secrag.search."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from ai_buffett_zo.secrag import (
    ChunkNode,
    FilingMetadata,
    FilingTree,
    SectionNode,
    save_tree,
    search,
)
from ai_buffett_zo.secrag.search import _tokenize


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
    chunks: list[ChunkNode] | None = None,
) -> SectionNode:
    return SectionNode(
        label=label,
        title=title,
        text=text,
        summary=summary,
        summary_data={"themes": themes or []},
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
        indexed_at=datetime(2026, 5, 6, tzinfo=UTC),
        indexer_model="test",
    )


# ---- Tokenizer -------------------------------------------------------------


def test_tokenize_drops_stopwords_and_short_tokens() -> None:
    assert _tokenize("the supply chain is at risk") == {"supply", "chain", "risk"}


def test_tokenize_lowercases() -> None:
    assert _tokenize("NVDA Supply") == {"nvda", "supply"}


def test_tokenize_empty_query() -> None:
    assert _tokenize("the and a") == set()


# ---- search() basic --------------------------------------------------------


def test_search_finds_keyword_in_text(tmp_path: Path) -> None:
    save_tree(
        tmp_path,
        _filing(
            "NVDA",
            [
                _section(
                    "risk_factors",
                    "Item 1A. Risk Factors",
                    "Our supply chain depends on a small number of accelerator suppliers.",
                ),
            ],
        ),
    )
    hits = search("supply chain risk", root=tmp_path)
    assert len(hits) == 1
    assert hits[0].ticker == "NVDA"
    assert hits[0].section_label == "risk_factors"
    assert hits[0].score > 0
    assert "supply" in hits[0].snippet.lower()


def test_search_returns_empty_on_no_match(tmp_path: Path) -> None:
    save_tree(
        tmp_path,
        _filing("NVDA", [_section("business", "Item 1", "We sell GPUs.")]),
    )
    assert search("aerospace", root=tmp_path) == []


def test_search_filters_by_ticker(tmp_path: Path) -> None:
    save_tree(
        tmp_path,
        _filing(
            "NVDA",
            [_section("risk_factors", "Item 1A", "Supply chain risk for NVDA.")],
        ),
    )
    save_tree(
        tmp_path,
        _filing(
            "AAPL",
            [_section("risk_factors", "Item 1A", "Supply chain risk for AAPL.")],
            filed=date(2025, 11, 1),
        ),
    )
    hits = search("supply", root=tmp_path, tickers=["NVDA"])
    assert len(hits) == 1
    assert hits[0].ticker == "NVDA"


def test_search_filters_by_section(tmp_path: Path) -> None:
    save_tree(
        tmp_path,
        _filing(
            "NVDA",
            [
                _section("business", "Item 1", "We sell semiconductor products."),
                _section("risk_factors", "Item 1A", "Semiconductor supply is constrained."),
            ],
        ),
    )
    hits = search("semiconductor", root=tmp_path, section_labels=["risk_factors"])
    assert len(hits) == 1
    assert hits[0].section_label == "risk_factors"


def test_search_top_k_caps_results(tmp_path: Path) -> None:
    sections = [
        _section("risk_factors", f"Item {i}", f"Supply chain text {i}.")
        for i in range(5)
    ]
    # 5 NVDA filings each with a section that matches
    for i in range(5):
        save_tree(
            tmp_path,
            _filing("NVDA", [sections[i]], filed=date(2026, 1, i + 1)),
        )
    hits = search("supply", root=tmp_path, top_k=3)
    assert len(hits) == 3


def test_search_themes_double_weighted(tmp_path: Path) -> None:
    """Section with the term in `themes` (which is double-weighted) should
    score higher than a section that only has it once in body text."""
    save_tree(
        tmp_path,
        _filing(
            "AAA",
            [
                _section(
                    "business",
                    "Item 1",
                    "Once we mentioned semiconductor.",
                    themes=["semiconductor"],
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
                    "business",
                    "Item 1",
                    "We mentioned semiconductor.",
                    themes=[],
                ),
            ],
            filed=date(2026, 1, 2),
        ),
    )
    hits = search("semiconductor", root=tmp_path)
    # AAA's themes contribute 2 extra matches; BBB has only the body match.
    aaa_score = next(h.score for h in hits if h.ticker == "AAA")
    bbb_score = next(h.score for h in hits if h.ticker == "BBB")
    assert aaa_score > bbb_score


def test_search_chunks_when_present(tmp_path: Path) -> None:
    """When a section has chunks, search should score chunks (not the section)
    so each chunk becomes its own hit and we don't double-count."""
    save_tree(
        tmp_path,
        _filing(
            "NVDA",
            [
                _section(
                    "risk_factors",
                    "Item 1A",
                    "Combined section text — supply chain plus tariffs and shipping.",
                    chunks=[
                        ChunkNode(0, "Supply chain text", "supply chain summary", {}),
                        ChunkNode(1, "Tariff exposure text", "tariff summary", {}),
                    ],
                ),
            ],
        ),
    )
    hits = search("tariff", root=tmp_path)
    assert len(hits) == 1
    assert "chunk1" in hits[0].path
    assert "Tariff" in hits[0].snippet or "tariff" in hits[0].snippet


def test_search_citation_includes_path(tmp_path: Path) -> None:
    save_tree(
        tmp_path,
        _filing(
            "NVDA",
            [_section("risk_factors", "Item 1A", "Supply chain risk.")],
        ),
    )
    hits = search("supply", root=tmp_path)
    assert hits[0].citation == "NVDA 10-K filed 2026-02-21 → risk_factors"


def test_search_empty_query_returns_empty(tmp_path: Path) -> None:
    save_tree(
        tmp_path,
        _filing("NVDA", [_section("business", "Item 1", "Anything.")]),
    )
    assert search("the and a", root=tmp_path) == []
