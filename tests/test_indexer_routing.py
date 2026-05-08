"""Tests for the indexer's full-index vs raw-fallback routing in process_one.

Verifies that:
- 10-K (FULL_INDEX_FORMS) → TreeBuilder is invoked (LLM summarization)
- 8-K / Form 4 (not in allowlist) → build_raw_tree path; TreeBuilder NOT invoked
- A short-form filing that exceeds the token safety net DOES get full indexing
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from ai_buffett_zo.indexer import IndexRequest, enqueue, load_status
from ai_buffett_zo.indexer import main as main_mod
from ai_buffett_zo.llm import ZoClient
from ai_buffett_zo.secrag import (
    FilingMetadata,
    FilingTree,
    Section,
    SectionNode,
)


def _logger() -> logging.Logger:
    return logging.getLogger("test_indexer_routing")


def _meta(form: str = "10-K", primary_doc: str = "x.htm") -> FilingMetadata:
    return FilingMetadata(
        cik="0000000000",
        ticker="NVDA",
        company="NVIDIA",
        form=form,
        filed=date(2026, 5, 7),
        period=date(2026, 5, 7),
        accession=f"acc-{form}",
        primary_doc=primary_doc,
        primary_doc_url=f"https://example/{primary_doc}",
    )


def _tree(metadata: FilingMetadata) -> FilingTree:
    return FilingTree(
        metadata=metadata,
        sections=[
            SectionNode(
                label="x", title="x", text="x", summary="x", summary_data={}, chunks=[]
            )
        ],
        indexed_at=datetime(2026, 5, 7, tzinfo=UTC),
        indexer_model="zo:test",
    )


def _section(text: str = "Some body text.") -> Section:
    return Section(
        label="filing-content",
        title="Filing content",
        text=text,
        char_start=0,
        char_end=len(text),
    )


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    metadata: FilingMetadata,
    sections: list[Section],
) -> dict[str, Any]:
    """Patch the secrag pipeline; return a dict that records calls."""
    captured: dict[str, Any] = {
        "fetched": [],
        "extracted": [],
        "tree_builder_invoked": False,
        "raw_tree_invoked": False,
    }

    def fake_fetch(ticker: str, *, form: str = "10-K") -> tuple[FilingMetadata, str]:
        captured["fetched"].append((ticker, form))
        return metadata, "<html>raw</html>"

    def fake_extract_for_form(content: str, *, form: str, content_type: str = "html") -> list[Section]:
        captured["extracted"].append((form, content_type))
        return sections

    class FakeBuilder:
        def __init__(self, client: Any, *, model: str = "x") -> None:
            self.client = client
            self.model = model

        def build(self, m: FilingMetadata, _sections: list[Section]) -> FilingTree:
            captured["tree_builder_invoked"] = True
            return _tree(m)

    def fake_build_raw_tree(m: FilingMetadata, _sections: list[Section]) -> FilingTree:
        captured["raw_tree_invoked"] = True
        return _tree(m)

    monkeypatch.setattr(main_mod, "fetch_filing", fake_fetch)
    monkeypatch.setattr(main_mod, "extract_sections_for_form", fake_extract_for_form)
    monkeypatch.setattr(main_mod, "TreeBuilder", FakeBuilder)
    monkeypatch.setattr(main_mod, "build_raw_tree", fake_build_raw_tree)
    return captured


def _process(
    tmp_path: Path,
    metadata: FilingMetadata,
    sections: list[Section],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    queue_root = tmp_path / "queue"
    sec_root = tmp_path / "sec"
    captured = _patch(monkeypatch, metadata=metadata, sections=sections)

    r = IndexRequest.new(metadata.ticker, metadata.form)
    enqueue(r, root=queue_root)

    main_mod.process_one(
        r.id,
        queue_root=queue_root,
        sec_root=sec_root,
        client=ZoClient(token="zo_sk_test"),
        default_model="zo:openai/gpt-5.4-mini",
        logger=_logger(),
    )
    return captured


# ---- 10-K → full LLM tree -------------------------------------------------


def test_10k_routes_to_tree_builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    md = _meta(form="10-K")
    captured = _process(tmp_path, md, [_section("Item 1A long content.")], monkeypatch)
    assert captured["tree_builder_invoked"] is True
    assert captured["raw_tree_invoked"] is False


def test_s1_routes_to_tree_builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    md = _meta(form="S-1")
    captured = _process(tmp_path, md, [_section("Prospectus content.")], monkeypatch)
    assert captured["tree_builder_invoked"] is True
    assert captured["raw_tree_invoked"] is False


def test_def14a_routes_to_tree_builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    md = _meta(form="DEF 14A")
    captured = _process(tmp_path, md, [_section("Proxy content.")], monkeypatch)
    assert captured["tree_builder_invoked"] is True
    assert captured["raw_tree_invoked"] is False


# ---- 8-K / Form 4 → raw fallback ------------------------------------------


def test_8k_short_routes_to_raw_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    md = _meta(form="8-K")
    captured = _process(tmp_path, md, [_section("Brief 8-K disclosure.")], monkeypatch)
    assert captured["raw_tree_invoked"] is True
    assert captured["tree_builder_invoked"] is False


def test_form_4_routes_to_raw_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    md = _meta(form="4", primary_doc="form4.xml")
    captured = _process(tmp_path, md, [_section("Form 4 transaction.")], monkeypatch)
    assert captured["raw_tree_invoked"] is True
    assert captured["tree_builder_invoked"] is False
    # And content_type was correctly detected from the .xml extension
    assert captured["extracted"][0][1] == "xml"


def test_amendment_form_4a_routes_to_raw_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    md = _meta(form="4/A", primary_doc="form4a.xml")
    captured = _process(tmp_path, md, [_section("Amended Form 4.")], monkeypatch)
    assert captured["raw_tree_invoked"] is True
    assert captured["tree_builder_invoked"] is False


# ---- Token safety net ------------------------------------------------------


def test_8k_oversize_triggers_full_indexing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A normally-raw form that exceeds the 15K-token safety net gets full-indexed."""
    md = _meta(form="8-K")
    big_text = "long content. " * 6000  # ~84K chars / 4 = ~21K tokens
    captured = _process(tmp_path, md, [_section(big_text)], monkeypatch)
    assert captured["tree_builder_invoked"] is True
    assert captured["raw_tree_invoked"] is False


# ---- Status persistence regardless of path --------------------------------


def test_status_completed_after_raw_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    md = _meta(form="8-K")
    _process(tmp_path, md, [_section("Brief 8-K.")], monkeypatch)
    sec_root = tmp_path / "sec"
    status = load_status(sec_root, "NVDA")
    assert status.last_request is not None
    assert status.last_request["state"] == "completed"
    # The filing was added to the indexed list
    assert len(status.filings) == 1
