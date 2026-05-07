"""Tests for ai_buffett_zo.evaluation.buffett_lens."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ai_buffett_zo.evaluation import LENS_DIMENSIONS, LensView, view
from ai_buffett_zo.secrag import (
    FilingMetadata,
    FilingTree,
    SectionNode,
    save_tree,
)


def _filing_with_sections(ticker: str, sections: list[tuple[str, str]]) -> FilingTree:
    metadata = FilingMetadata(
        cik="0000000000",
        ticker=ticker,
        company=f"{ticker} Inc.",
        form="10-K",
        filed=date(2026, 2, 21),
        period=date(2026, 1, 26),
        accession=f"acc-{ticker}",
        primary_doc="x.htm",
        primary_doc_url=f"https://example/{ticker}.htm",
    )
    return FilingTree(
        metadata=metadata,
        sections=[
            SectionNode(
                label=label,
                title=f"Item {label}",
                text=text,
                summary=text[:60],
                summary_data={"themes": []},
                chunks=[],
            )
            for label, text in sections
        ],
        indexed_at=datetime(2026, 5, 6, tzinfo=UTC),
        indexer_model="zo:test",
    )


def test_lens_dimensions_table_has_four_dimensions() -> None:
    assert set(LENS_DIMENSIONS.keys()) == {"moat", "management", "financials", "risks"}
    for spec in LENS_DIMENSIONS.values():
        assert spec.title
        assert spec.query
        assert spec.sections
        assert spec.top_k > 0


def test_lens_section_filters_match_secrag_labels() -> None:
    """Sections in the lens specs must be ones the indexer actually emits."""
    valid = {"business", "risk_factors", "mdna", "financial_statements"}
    for spec in LENS_DIMENSIONS.values():
        for s in spec.sections:
            assert s in valid, f"unknown section in lens spec: {s}"


def test_view_returns_one_lensview_per_dimension(tmp_path: Path) -> None:
    save_tree(tmp_path, _filing_with_sections("NVDA", [("business", "We sell GPUs.")]))
    out = view("NVDA", sec_root=tmp_path)
    assert len(out) == 4
    assert [v.dimension for v in out] == ["moat", "management", "financials", "risks"]
    for v in out:
        assert isinstance(v, LensView)
        assert v.title


def test_view_with_dimension_filter(tmp_path: Path) -> None:
    save_tree(tmp_path, _filing_with_sections("NVDA", [("business", "We sell GPUs.")]))
    out = view("NVDA", sec_root=tmp_path, dimensions=["moat", "risks"])
    assert [v.dimension for v in out] == ["moat", "risks"]


def test_view_unknown_dimension_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown lens dimension"):
        view("NVDA", sec_root=tmp_path, dimensions=["bogus"])


def test_view_empty_corpus_returns_empty_hits(tmp_path: Path) -> None:
    """No filings indexed yet — each LensView still appears with hits=[]."""
    out = view("NVDA", sec_root=tmp_path)
    assert len(out) == 4
    assert all(v.hits == [] for v in out)


def test_view_filters_by_ticker(tmp_path: Path) -> None:
    """Only the requested ticker's filings are searched."""
    save_tree(tmp_path, _filing_with_sections("NVDA", [("business", "Supply chain risk.")]))
    save_tree(
        tmp_path,
        _filing_with_sections("AAPL", [("business", "Supply chain risk.")]),
    )
    out = view("NVDA", sec_root=tmp_path, dimensions=["moat"])
    assert len(out) == 1
    for h in out[0].hits:
        assert h.ticker == "NVDA"


def test_view_moat_dimension_pulls_from_business_and_mdna(tmp_path: Path) -> None:
    save_tree(
        tmp_path,
        _filing_with_sections(
            "NVDA",
            [
                ("business", "Our competitive advantage is our scale and software ecosystem."),
                ("risk_factors", "Competitive advantage is at risk from new entrants."),
                ("mdna", "Pricing power has expanded as customers face switching costs."),
            ],
        ),
    )
    out = view("NVDA", sec_root=tmp_path, dimensions=["moat"])
    assert len(out) == 1
    sections_hit = {h.section_label for h in out[0].hits}
    # Moat lens should NOT have pulled risk_factors content.
    assert sections_hit.issubset({"business", "mdna"})


def test_view_risks_dimension_pulls_from_risk_factors_only(tmp_path: Path) -> None:
    save_tree(
        tmp_path,
        _filing_with_sections(
            "NVDA",
            [
                ("business", "Customer concentration in cloud providers."),
                ("risk_factors", "Customer concentration risk: top 3 customers are 39% of revenue."),
            ],
        ),
    )
    out = view("NVDA", sec_root=tmp_path, dimensions=["risks"])
    assert len(out) == 1
    sections_hit = {h.section_label for h in out[0].hits}
    assert sections_hit == {"risk_factors"}


def test_view_top_k_respected(tmp_path: Path) -> None:
    """Synthesize many chunked sections so top_k actually clips."""
    from ai_buffett_zo.secrag import ChunkNode

    metadata = FilingMetadata(
        cik="0000000000",
        ticker="NVDA",
        company="NVIDIA",
        form="10-K",
        filed=date(2026, 2, 21),
        period=date(2026, 1, 26),
        accession="acc-NVDA",
        primary_doc="x.htm",
        primary_doc_url="https://example/x.htm",
    )
    section = SectionNode(
        label="risk_factors",
        title="Item 1A",
        text="risk regulation supply chain " * 5,
        summary="aggregate",
        summary_data={"themes": []},
        chunks=[
            ChunkNode(
                chunk_index=i,
                text=f"Chunk {i}: risk regulation supply chain competition customer concentration {'litigation ' * (i + 1)}",
                summary="",
                summary_data={"themes": []},
            )
            for i in range(10)
        ],
    )
    tree = FilingTree(
        metadata=metadata,
        sections=[section],
        indexed_at=datetime(2026, 5, 6, tzinfo=UTC),
        indexer_model="zo:test",
    )
    save_tree(tmp_path, tree)
    out = view("NVDA", sec_root=tmp_path, dimensions=["risks"])
    risks_spec = LENS_DIMENSIONS["risks"]
    assert len(out[0].hits) <= risks_spec.top_k
