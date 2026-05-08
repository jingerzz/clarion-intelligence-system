"""Tests for ai_buffett_zo.secrag.tree.build_raw_tree (no-LLM fallback)."""

from __future__ import annotations

from datetime import date

from ai_buffett_zo.secrag import (
    FilingMetadata,
    Section,
    build_raw_tree,
)
from ai_buffett_zo.secrag.tree import RAW_INDEXER_MODEL


def _meta(form: str = "8-K") -> FilingMetadata:
    return FilingMetadata(
        cik="0000000000",
        ticker="NVDA",
        company="NVIDIA Inc.",
        form=form,
        filed=date(2026, 5, 7),
        period=date(2026, 5, 7),
        accession="acc-1",
        primary_doc="form8k.htm",
        primary_doc_url="https://example/form8k.htm",
    )


def _section(label: str = "filing-content", text: str = "Body text.") -> Section:
    return Section(
        label=label,
        title=label.replace("-", " ").title(),
        text=text,
        char_start=0,
        char_end=len(text),
    )


def test_build_raw_tree_no_llm_calls_no_summaries() -> None:
    """Raw mode: text preserved verbatim, summary fields empty, no chunks."""
    sections = [_section("filing-content", "8-K body text.")]
    tree = build_raw_tree(_meta(), sections)
    assert len(tree.sections) == 1
    s = tree.sections[0]
    assert s.text == "8-K body text."
    assert s.summary == ""
    assert s.summary_data == {}
    assert s.chunks == []
    assert s.label == "filing-content"


def test_build_raw_tree_indexer_model_is_sentinel() -> None:
    """The indexer_model field carries a sentinel so meta.json can identify
    raw-stored filings without decompressing the tree."""
    tree = build_raw_tree(_meta(), [_section()])
    assert tree.indexer_model == RAW_INDEXER_MODEL
    assert tree.indexer_model == "raw-no-llm"


def test_build_raw_tree_preserves_all_sections() -> None:
    sections = [
        _section("section-a", "First."),
        _section("section-b", "Second."),
        _section("section-c", "Third."),
    ]
    tree = build_raw_tree(_meta(), sections)
    assert [s.label for s in tree.sections] == ["section-a", "section-b", "section-c"]
    assert [s.text for s in tree.sections] == ["First.", "Second.", "Third."]


def test_build_raw_tree_empty_sections_produces_empty_tree() -> None:
    tree = build_raw_tree(_meta(), [])
    assert tree.sections == []
    assert tree.indexer_model == RAW_INDEXER_MODEL


def test_build_raw_tree_metadata_round_trips() -> None:
    md = _meta(form="Form 4")
    tree = build_raw_tree(md, [_section()])
    assert tree.metadata.form == "Form 4"
    assert tree.metadata.ticker == "NVDA"
    assert tree.metadata.accession == "acc-1"
