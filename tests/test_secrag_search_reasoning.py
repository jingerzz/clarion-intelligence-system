"""Tests for the Stage 2 LLM reasoning path in secrag.search.

The keyword-only path is exercised by test_secrag_search.py; this file covers:
- Reasoning escalation when the top keyword score is below the threshold
- Skipping reasoning when keyword scores are strong enough
- Skipping silently when no client is available
- Catalog construction (ticker_filter, label_filter, chunked vs flat sections)
- LLM result merging with keyword hits (no duplicates by path)
- Repair pass tolerating LLM output variants (paths/results aliasing)
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ai_buffett_zo.llm import AskResult
from ai_buffett_zo.secrag import (
    ChunkNode,
    FilingMetadata,
    FilingTree,
    SectionNode,
    save_tree,
)
from ai_buffett_zo.secrag.search import (
    LLM_HIT_SCORE,
    _build_catalog,
    search,
)


def _meta(ticker: str = "NVDA", accession: str | None = None) -> FilingMetadata:
    return FilingMetadata(
        cik="0000000000",
        ticker=ticker,
        company=f"{ticker} Inc.",
        form="10-K",
        filed=date(2026, 2, 21),
        period=date(2026, 1, 26),
        accession=accession or f"acc-{ticker}",
        primary_doc="x.htm",
        primary_doc_url=f"https://example/{ticker}.htm",
    )


def _section(
    label: str,
    text: str,
    *,
    summary: str = "",
    title: str | None = None,
    chunks: list[ChunkNode] | None = None,
) -> SectionNode:
    return SectionNode(
        label=label,
        title=title or label.replace("_", " ").title(),
        text=text,
        summary=summary,
        summary_data={},
        chunks=chunks or [],
    )


def _filing(
    ticker: str,
    sections: list[SectionNode],
    *,
    accession: str | None = None,
) -> FilingTree:
    return FilingTree(
        metadata=_meta(ticker, accession),
        sections=sections,
        indexed_at=datetime(2026, 5, 7, tzinfo=UTC),
        indexer_model="zo:test",
    )


class FakeClient:
    """Stand-in ZoClient that returns a scripted reasoning response."""

    def __init__(self, *, selected_paths: list[str] | None = None, ok: bool = True) -> None:
        self.selected_paths = selected_paths or []
        self.ok = ok
        self.call_count = 0
        self.last_prompt = ""

    def _token(self) -> str:
        return "zo_sk_fake"

    def ask(self, *, input=None, output_format=None, repair=None, **kwargs) -> AskResult:  # noqa: A002
        self.call_count += 1
        self.last_prompt = input or ""
        if not self.ok:
            return AskResult(
                ok=False, data=None, raw=None, elapsed_s=0.0, model="", error="boom"
            )
        return AskResult(
            ok=True,
            data={"selected_paths": self.selected_paths, "rationale": "test"},
            raw={"selected_paths": self.selected_paths, "rationale": "test"},
            elapsed_s=0.01,
            model="zo:test",
        )


# ---- Reasoning gating ------------------------------------------------------


def test_reasoning_skipped_when_keyword_score_strong(tmp_path: Path) -> None:
    """A query that hits ≥ threshold (3) should NOT call the LLM."""
    save_tree(
        tmp_path,
        _filing(
            "NVDA",
            [_section("risk_factors", "supply chain supply chain supply chain")],
        ),
    )
    client = FakeClient(selected_paths=["NVDA/acc-NVDA/risk_factors"])
    hits = search("supply", root=tmp_path, client=client)
    assert client.call_count == 0  # not escalated
    assert len(hits) >= 1
    assert hits[0].ticker == "NVDA"


def test_reasoning_runs_when_keyword_score_weak(tmp_path: Path) -> None:
    """A query that gets only 1 keyword hit should escalate to LLM."""
    save_tree(
        tmp_path,
        _filing(
            "NVDA",
            [
                _section("risk_factors", "we discuss supply once.", summary="supply chain risk discussion"),
            ],
        ),
    )
    client = FakeClient(selected_paths=["NVDA/acc-NVDA/risk_factors"])
    search("supply", root=tmp_path, client=client)
    assert client.call_count == 1


def test_reasoning_runs_when_no_keyword_hits(tmp_path: Path) -> None:
    """Empty keyword result should still escalate to LLM (which can find
    semantically related sections)."""
    save_tree(
        tmp_path,
        _filing("NVDA", [_section("business", "We make GPUs.", summary="business overview")]),
    )
    client = FakeClient(selected_paths=["NVDA/acc-NVDA/business"])
    hits = search("aerospace", root=tmp_path, client=client)
    assert client.call_count == 1
    # LLM-selected hit comes back even though keyword found nothing
    assert any(h.ticker == "NVDA" for h in hits)


def test_reasoning_disabled_via_flag_skips_llm(tmp_path: Path) -> None:
    """reasoning=False should NEVER call the LLM, even on weak keyword."""
    save_tree(tmp_path, _filing("NVDA", [_section("business", "we discuss supply once.")]))
    client = FakeClient(selected_paths=["NVDA/acc-NVDA/business"])
    search("supply", root=tmp_path, reasoning=False, client=client)
    assert client.call_count == 0


def test_reasoning_skipped_silently_when_no_client_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ZO_API_KEY and no ZO_CLIENT_IDENTITY_TOKEN → reasoning silently skipped."""
    monkeypatch.delenv("ZO_API_KEY", raising=False)
    monkeypatch.delenv("ZO_CLIENT_IDENTITY_TOKEN", raising=False)
    save_tree(tmp_path, _filing("NVDA", [_section("business", "we discuss supply once.")]))
    # Don't pass a client — and env has no token
    hits = search("supply", root=tmp_path)
    # Returns whatever keyword found (1 hit) without erroring
    assert isinstance(hits, list)


def test_reasoning_threshold_configurable(tmp_path: Path) -> None:
    """A higher threshold escalates more aggressively."""
    save_tree(
        tmp_path,
        _filing(
            "NVDA",
            [_section("risk_factors", "supply chain supply chain supply chain")],
        ),
    )
    client = FakeClient(selected_paths=[])
    # Default threshold 3 → no escalation. Custom threshold 100 → escalate.
    search("supply", root=tmp_path, client=client, reasoning_threshold=100)
    assert client.call_count == 1


# ---- LLM result merging ----------------------------------------------------


def test_llm_hits_score_at_llm_score_constant(tmp_path: Path) -> None:
    save_tree(tmp_path, _filing("NVDA", [_section("business", "x", summary="overview")]))
    client = FakeClient(selected_paths=["NVDA/acc-NVDA/business"])
    hits = search("aerospace", root=tmp_path, client=client)
    nvda_hit = next(h for h in hits if h.ticker == "NVDA")
    assert nvda_hit.score == LLM_HIT_SCORE


def test_llm_hits_dedupe_against_keyword_hits(tmp_path: Path) -> None:
    """If keyword found a section AND the LLM also picks it, no duplicate."""
    save_tree(
        tmp_path,
        _filing(
            "NVDA",
            [_section("risk_factors", "we discuss supply once.", summary="supply chain")],
        ),
    )
    client = FakeClient(selected_paths=["NVDA/acc-NVDA/risk_factors"])
    hits = search("supply", root=tmp_path, client=client)
    nvda_paths = [(h.accession, h.path) for h in hits if h.ticker == "NVDA"]
    assert len(nvda_paths) == len(set(nvda_paths))  # no duplicates


def test_llm_hits_for_chunked_sections(tmp_path: Path) -> None:
    """LLM should be able to select a specific chunk path (label/chunkN)."""
    chunks = [
        ChunkNode(0, "First chunk text.", "first chunk summary", {"themes": []}),
        ChunkNode(1, "Second chunk text — aerospace mention.", "second chunk summary", {"themes": []}),
    ]
    save_tree(
        tmp_path,
        _filing(
            "NVDA",
            [
                _section(
                    "risk_factors",
                    "Combined risk_factors section text.",
                    summary="overall risk overview",
                    chunks=chunks,
                )
            ],
        ),
    )
    client = FakeClient(selected_paths=["NVDA/acc-NVDA/risk_factors/chunk1"])
    hits = search("nonsense-zzz", root=tmp_path, client=client)  # no keyword match
    assert any(h.path == "risk_factors/chunk1" for h in hits)


def test_llm_silently_skipped_when_ask_fails(tmp_path: Path) -> None:
    """If /zo/ask returns ok=False, we just return the keyword results."""
    save_tree(tmp_path, _filing("NVDA", [_section("business", "we discuss supply once.")]))
    client = FakeClient(selected_paths=[], ok=False)
    hits = search("supply", root=tmp_path, client=client)
    assert isinstance(hits, list)


def test_llm_unknown_paths_in_response_are_dropped(tmp_path: Path) -> None:
    """If the LLM hallucinates a path that's not in the catalog, ignore it."""
    save_tree(tmp_path, _filing("NVDA", [_section("business", "x", summary="overview")]))
    client = FakeClient(
        selected_paths=[
            "NVDA/acc-NVDA/business",
            "NVDA/acc-NVDA/this-section-does-not-exist",
            "FAKE/acc-FAKE/whatever",
        ]
    )
    hits = search("aerospace", root=tmp_path, client=client)
    assert any(h.ticker == "NVDA" and h.section_label == "business" for h in hits)
    assert not any(h.section_label == "this-section-does-not-exist" for h in hits)
    assert not any(h.ticker == "FAKE" for h in hits)


# ---- Catalog construction --------------------------------------------------


def test_catalog_builds_one_line_per_section(tmp_path: Path) -> None:
    save_tree(
        tmp_path,
        _filing("NVDA", [_section("business", "x", summary="overview"), _section("mdna", "y", summary="mdna summary")]),
    )
    lines, index = _build_catalog(tmp_path, ticker_filter=None, label_filter=None)
    assert len(lines) == 2
    paths = list(index.keys())
    assert "NVDA/acc-NVDA/business" in paths
    assert "NVDA/acc-NVDA/mdna" in paths


def test_catalog_emits_chunk_paths_when_chunks_present(tmp_path: Path) -> None:
    chunks = [
        ChunkNode(0, "x", "chunk0 summary", {"themes": []}),
        ChunkNode(1, "y", "chunk1 summary", {"themes": []}),
    ]
    save_tree(tmp_path, _filing("NVDA", [_section("risk_factors", "combined", chunks=chunks)]))
    lines, index = _build_catalog(tmp_path, ticker_filter=None, label_filter=None)
    paths = list(index.keys())
    assert "NVDA/acc-NVDA/risk_factors/chunk0" in paths
    assert "NVDA/acc-NVDA/risk_factors/chunk1" in paths
    # Parent section path is NOT in catalog when chunks are present (avoid double-listing)
    assert "NVDA/acc-NVDA/risk_factors" not in paths


def test_catalog_respects_ticker_filter(tmp_path: Path) -> None:
    save_tree(tmp_path, _filing("NVDA", [_section("business", "x", summary="o")]))
    save_tree(tmp_path, _filing("AAPL", [_section("business", "y", summary="o")]))
    lines, index = _build_catalog(tmp_path, ticker_filter={"NVDA"}, label_filter=None)
    assert all("NVDA/" in p for p in index.keys())
    assert not any("AAPL/" in p for p in index.keys())


def test_catalog_respects_label_filter(tmp_path: Path) -> None:
    save_tree(
        tmp_path,
        _filing("NVDA", [_section("business", "x", summary="o"), _section("risk_factors", "y", summary="o")]),
    )
    lines, index = _build_catalog(tmp_path, ticker_filter=None, label_filter={"risk_factors"})
    paths = list(index.keys())
    assert all("risk_factors" in p for p in paths)
    assert not any("business" in p for p in paths)


def test_catalog_empty_when_no_indexed_filings(tmp_path: Path) -> None:
    lines, index = _build_catalog(tmp_path / "nope", ticker_filter=None, label_filter=None)
    assert lines == []
    assert index == {}


# ---- Prompt structure ------------------------------------------------------


def test_reasoning_prompt_includes_query_and_catalog(tmp_path: Path) -> None:
    save_tree(tmp_path, _filing("NVDA", [_section("business", "x", summary="overview")]))
    client = FakeClient(selected_paths=[])
    search("supply chain risk", root=tmp_path, client=client)
    assert "supply chain risk" in client.last_prompt
    assert "NVDA/acc-NVDA/business" in client.last_prompt
    assert "CATALOG" in client.last_prompt or "catalog" in client.last_prompt.lower()


# ---- Backward compat -------------------------------------------------------


def test_existing_callers_with_no_client_still_work(tmp_path: Path) -> None:
    """Existing call sites that don't pass `client` should not regress.

    With strong keyword match and no env token, reasoning is skipped silently
    and keyword results are returned — same as before B-6d.
    """
    save_tree(
        tmp_path,
        _filing(
            "NVDA",
            [_section("risk_factors", "supply chain supply chain supply chain")],
        ),
    )
    hits = search("supply", root=tmp_path)
    assert len(hits) >= 1
