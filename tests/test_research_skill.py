"""Tests for skills/clarion-sec-research/scripts/research.py.

Each subcommand is exercised with tmp_path-rooted queue/sec dirs so we don't
touch the user's real workspace. CLARION_QUEUE_ROOT and CLARION_SEC_ROOT
overrides are how the script's roots are wired.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ai_buffett_zo.indexer import (
    FilingStatus,
    TickerStatus,
    save_status,
)
from ai_buffett_zo.secrag import (
    FilingMetadata,
    FilingTree,
    SectionNode,
    save_tree,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_PATH = REPO_ROOT / "skills" / "clarion-sec-research" / "scripts" / "research.py"


@pytest.fixture(scope="module")
def research_mod():
    spec = importlib.util.spec_from_file_location("clarion_research", RESEARCH_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["clarion_research"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Return (queue_root, sec_root) and wire env overrides."""
    queue_root = tmp_path / "queue"
    sec_root = tmp_path / "sec"
    monkeypatch.setenv("CLARION_QUEUE_ROOT", str(queue_root))
    monkeypatch.setenv("CLARION_SEC_ROOT", str(sec_root))
    return queue_root, sec_root


def _make_filing(
    ticker: str,
    body: str = "Supply chain depends on a small number of suppliers.",
    *,
    section_label: str = "risk_factors",
    accession: str | None = None,
) -> FilingTree:
    accession = accession or f"acc-{ticker}"
    metadata = FilingMetadata(
        cik="0000000000",
        ticker=ticker,
        company=f"{ticker} Inc.",
        form="10-K",
        filed=date(2026, 2, 21),
        period=date(2026, 1, 26),
        accession=accession,
        primary_doc="x.htm",
        primary_doc_url=f"https://example/{ticker}.htm",
    )
    return FilingTree(
        metadata=metadata,
        sections=[
            SectionNode(
                label=section_label,
                title=f"Item {section_label}",
                text=body,
                summary=body[:60],
                summary_data={"themes": []},
                chunks=[],
            )
        ],
        indexed_at=datetime(2026, 5, 6, tzinfo=UTC),
        indexer_model="zo:test",
    )


# ---- cmd_index -------------------------------------------------------------


def test_cmd_index_creates_queue_file(
    research_mod, roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    queue_root, _ = roots
    args = argparse.Namespace(ticker="NVDA", form="10-K")

    rc = research_mod.cmd_index(args)
    assert rc == 0

    files = list(queue_root.glob("*.json"))
    assert len(files) == 1
    body = json.loads(files[0].read_text())
    assert body["ticker"] == "NVDA"
    assert body["form"] == "10-K"

    captured = capsys.readouterr()
    assert "NVDA" in captured.out
    assert "Queued" in captured.out
    assert "Request ID" in captured.out


def test_cmd_index_passes_form_through(
    research_mod, roots: tuple[Path, Path]
) -> None:
    queue_root, _ = roots
    research_mod.cmd_index(argparse.Namespace(ticker="AAPL", form="10-Q"))
    body = json.loads(next(queue_root.glob("*.json")).read_text())
    assert body["form"] == "10-Q"


# ---- cmd_status ------------------------------------------------------------


def test_cmd_status_empty_when_no_status_file(
    research_mod, roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(ticker="NVDA")
    rc = research_mod.cmd_status(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "NVDA" in out
    assert "No filings indexed" in out


def test_cmd_status_shows_filings_and_request(
    research_mod, roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, sec_root = roots
    status = TickerStatus(ticker="NVDA")
    status.merge_filing(
        FilingStatus(
            accession="acc-1",
            form="10-K",
            filed="2026-02-21",
            indexed_at="2026-05-06T12:00:00+00:00",
            status="indexed",
        )
    )
    status.update_request(form="10-K", state="completed")
    save_status(sec_root, status)

    rc = research_mod.cmd_status(argparse.Namespace(ticker="NVDA"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Last request" in out
    assert "completed" in out
    assert "Indexed filings" in out
    assert "acc-1" in out


def test_cmd_status_surfaces_error_field(
    research_mod, roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, sec_root = roots
    status = TickerStatus(ticker="FAKE")
    status.update_request(form="10-K", state="failed", error="ticker not in SEC tickers map")
    save_status(sec_root, status)

    research_mod.cmd_status(argparse.Namespace(ticker="FAKE"))
    out = capsys.readouterr().out
    assert "failed" in out
    assert "ticker not in SEC" in out


# ---- cmd_search ------------------------------------------------------------


def test_cmd_search_no_corpus_suggests_indexing(
    research_mod, roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(
        query="supply chain", tickers=None, sections=None, top_k=10, top_show=5
    )
    research_mod.cmd_search(args)
    out = capsys.readouterr().out
    assert "No filings indexed yet" in out


def test_cmd_search_no_hits_for_specified_tickers_suggests_indexing(
    research_mod, roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, sec_root = roots
    save_tree(sec_root, _make_filing("XYZ"))  # corpus exists, but not NVDA
    args = argparse.Namespace(
        query="aerospace defense",
        tickers="NVDA",
        sections=None,
        top_k=10,
        top_show=5,
    )
    research_mod.cmd_search(args)
    out = capsys.readouterr().out
    assert "no matches" in out.lower()
    assert "index NVDA" in out


def test_cmd_search_returns_hits_with_table_and_snippets(
    research_mod, roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, sec_root = roots
    save_tree(sec_root, _make_filing("NVDA"))
    args = argparse.Namespace(
        query="supply chain", tickers=None, sections=None, top_k=10, top_show=5
    )
    rc = research_mod.cmd_search(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "NVDA" in out
    assert "10-K" in out
    assert "**Top results**" in out
    assert "supply chain" in out.lower()


def test_cmd_search_filters_by_ticker(
    research_mod, roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, sec_root = roots
    save_tree(sec_root, _make_filing("NVDA", "Supply chain risk for NVDA."))
    save_tree(sec_root, _make_filing("AAPL", "Supply chain risk for AAPL."))
    args = argparse.Namespace(
        query="supply", tickers="NVDA", sections=None, top_k=10, top_show=5
    )
    research_mod.cmd_search(args)
    out = capsys.readouterr().out
    assert "NVDA" in out
    assert "AAPL" not in out


def test_cmd_search_subtitle_lists_filters(
    research_mod, roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, sec_root = roots
    save_tree(sec_root, _make_filing("NVDA"))
    args = argparse.Namespace(
        query="supply",
        tickers="NVDA",
        sections="risk_factors",
        top_k=10,
        top_show=5,
    )
    research_mod.cmd_search(args)
    out = capsys.readouterr().out
    assert "tickers:" in out
    assert "sections:" in out


# ---- helpers ---------------------------------------------------------------


def test_split_csv(research_mod) -> None:
    assert research_mod._split_csv(None) is None
    assert research_mod._split_csv("") is None
    assert research_mod._split_csv("a,b,c") == ["a", "b", "c"]
    assert research_mod._split_csv("a, b ,c") == ["a", "b", "c"]
    assert research_mod._split_csv(", , ,") is None or research_mod._split_csv(", , ,") == []
