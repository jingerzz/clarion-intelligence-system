"""Tests for ai_buffett_zo.secrag.storage."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from ai_buffett_zo.secrag import (
    ChunkNode,
    FilingMetadata,
    FilingTree,
    SectionNode,
    is_indexed,
    list_indexed,
    load_raw,
    load_tree,
    save_raw,
    save_tree,
)


def _meta(ticker: str = "NVDA", form: str = "10-K", filed: date = date(2026, 2, 21)) -> FilingMetadata:
    return FilingMetadata(
        cik="0001045810",
        ticker=ticker,
        company="NVIDIA Corp",
        form=form,
        filed=filed,
        period=filed,
        accession=f"acc-{ticker}-{filed.isoformat()}",
        primary_doc="doc.htm",
        primary_doc_url="https://example/doc.htm",
    )


def _tree(metadata: FilingMetadata | None = None) -> FilingTree:
    metadata = metadata or _meta()
    section = SectionNode(
        label="risk_factors",
        title="Item 1A. Risk Factors",
        text="Risks include supply chain and demand volatility.",
        summary="Supply and demand risks.",
        summary_data={"key_points": ["supply chain", "demand"], "severity": 3},
        chunks=[
            ChunkNode(
                chunk_index=0,
                text="Chunk text 0",
                summary="Chunk 0 summary",
                summary_data={"severity": 2},
            ),
        ],
    )
    return FilingTree(
        metadata=metadata,
        sections=[section],
        indexed_at=datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC),
        indexer_model="zo:openai/gpt-5.4-mini",
    )


def test_raw_html_roundtrip(tmp_path: Path) -> None:
    metadata = _meta()
    html = "<html>filing body</html>" * 100
    path = save_raw(tmp_path, metadata, html)
    assert path.exists()
    loaded = load_raw(tmp_path, metadata.ticker, metadata.accession)
    assert loaded == html


def test_tree_roundtrip_preserves_all_fields(tmp_path: Path) -> None:
    tree = _tree()
    save_tree(tmp_path, tree)
    loaded = load_tree(tmp_path, tree.metadata.ticker, tree.metadata.accession)

    assert loaded.metadata == tree.metadata
    assert loaded.indexer_model == tree.indexer_model
    assert len(loaded.sections) == 1

    s = loaded.sections[0]
    assert s.label == "risk_factors"
    assert s.text == tree.sections[0].text
    assert s.summary_data == tree.sections[0].summary_data
    assert len(s.chunks) == 1
    assert s.chunks[0].text == "Chunk text 0"


def test_save_tree_writes_meta_alongside(tmp_path: Path) -> None:
    tree = _tree()
    save_tree(tmp_path, tree)
    meta_path = tmp_path / "NVDA" / f"{tree.metadata.accession}.meta.json"
    assert meta_path.exists()
    # Meta must be small and readable without decompression
    raw = meta_path.read_text()
    assert "NVDA" in raw
    assert "risk_factors" in raw  # section_labels


def test_list_indexed_empty_when_root_missing(tmp_path: Path) -> None:
    assert list_indexed(tmp_path / "nope") == []


def test_list_indexed_returns_metadata(tmp_path: Path) -> None:
    save_tree(tmp_path, _tree(_meta("NVDA", "10-K", date(2026, 2, 21))))
    save_tree(tmp_path, _tree(_meta("NVDA", "10-Q", date(2026, 4, 30))))
    save_tree(tmp_path, _tree(_meta("AAPL", "10-K", date(2025, 11, 1))))

    all_filings = list_indexed(tmp_path)
    tickers = {m.ticker for m in all_filings}
    assert tickers == {"NVDA", "AAPL"}


def test_list_indexed_filtered_by_ticker(tmp_path: Path) -> None:
    save_tree(tmp_path, _tree(_meta("NVDA", "10-K", date(2026, 2, 21))))
    save_tree(tmp_path, _tree(_meta("AAPL", "10-K", date(2025, 11, 1))))
    nvda_only = list_indexed(tmp_path, ticker="NVDA")
    assert len(nvda_only) == 1
    assert nvda_only[0].ticker == "NVDA"


def test_list_indexed_sorts_newest_first(tmp_path: Path) -> None:
    save_tree(tmp_path, _tree(_meta("NVDA", "10-K", date(2024, 2, 21))))
    save_tree(tmp_path, _tree(_meta("NVDA", "10-K", date(2026, 2, 21))))
    save_tree(tmp_path, _tree(_meta("NVDA", "10-K", date(2025, 2, 21))))
    listed = list_indexed(tmp_path, ticker="NVDA")
    dates = [m.filed for m in listed]
    assert dates == sorted(dates, reverse=True)


def test_is_indexed(tmp_path: Path) -> None:
    metadata = _meta()
    assert not is_indexed(tmp_path, metadata.ticker, metadata.accession)
    save_tree(tmp_path, _tree(metadata))
    assert is_indexed(tmp_path, metadata.ticker, metadata.accession)
