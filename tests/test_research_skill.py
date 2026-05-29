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


def _ns(ticker: str, **kwargs) -> argparse.Namespace:
    """Build a Namespace matching the new cmd_index signature, with sane defaults."""
    return argparse.Namespace(
        ticker=ticker,
        form=kwargs.get("form"),
        days=kwargs.get("days"),
        count=kwargs.get("count"),
        latest=kwargs.get("latest", False),
        force=kwargs.get("force", False),
        profile=kwargs.get("profile", "eval"),
    )


def _fm(
    ticker: str, form: str, filed: date, accession: str
) -> FilingMetadata:
    return FilingMetadata(
        cik="0001045810",
        ticker=ticker,
        company=f"{ticker} Inc.",
        form=form,
        filed=filed,
        period=filed,
        accession=accession,
        primary_doc=f"{accession}.htm",
        primary_doc_url=f"https://example/{accession}.htm",
    )


def test_cmd_index_latest_creates_single_queue_file(
    research_mod, roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """The --latest path is the legacy single-filing mode (no SEC EDGAR call)."""
    queue_root, _ = roots
    args = _ns("NVDA", form="10-K", latest=True)

    rc = research_mod.cmd_index(args)
    assert rc == 0

    files = list(queue_root.glob("*.json"))
    assert len(files) == 1
    body = json.loads(files[0].read_text())
    assert body["ticker"] == "NVDA"
    assert body["form"] == "10-K"
    assert body.get("accession") is None, "legacy --latest path leaves accession unset"

    captured = capsys.readouterr()
    assert "NVDA" in captured.out
    assert "Queued" in captured.out
    assert "most recent 10-K" in captured.out


def test_cmd_index_latest_requires_form(
    research_mod, roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    rc = research_mod.cmd_index(_ns("NVDA", latest=True))
    assert rc == 2
    assert "--latest requires --form" in capsys.readouterr().err


def test_cmd_index_latest_mutually_exclusive_with_days(
    research_mod, roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    rc = research_mod.cmd_index(_ns("NVDA", form="4", days=180, latest=True))
    assert rc == 2
    assert "mutually exclusive" in capsys.readouterr().err


def test_cmd_index_form_scoped_enqueues_all_in_window(
    research_mod,
    roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`index NVDA --form 4` should enqueue every Form 4 in the default window —
    the bug fix from the issue (vs. old single-most-recent behavior)."""
    queue_root, _ = roots
    fake = [
        _fm("NVDA", "4", date(2026, 5, 4), "0001045810-26-000099"),
        _fm("NVDA", "4", date(2026, 3, 4), "0001045810-26-000050"),
        _fm("NVDA", "4", date(2026, 3, 2), "0001045810-26-000049"),
    ]

    captured_kwargs: dict = {}

    def fake_list(ticker: str, **kwargs):
        captured_kwargs.update(kwargs)
        return fake

    monkeypatch.setattr(research_mod, "list_recent_filings", fake_list)

    rc = research_mod.cmd_index(_ns("NVDA", form="4"))
    assert rc == 0

    files = sorted(queue_root.glob("*.json"))
    assert len(files) == 3, "all three Form 4s should be enqueued, not just the most recent"
    accessions = sorted(json.loads(f.read_text())["accession"] for f in files)
    assert accessions == [
        "0001045810-26-000049",
        "0001045810-26-000050",
        "0001045810-26-000099",
    ]
    assert captured_kwargs == {"form": "4", "since_days": 90, "limit": None}

    out = capsys.readouterr().out
    assert "3 filings" in out
    assert "0001045810-26-000099" in out


# Shared filing set for the composite-profile tests: core + events + low-signal.
def _composite_fake_list(ticker, *, form=None, since_days=None, limit=None, **kwargs):
    recent_10k = _fm("NVDA", "10-K", date(2026, 2, 21), "ACC-10K-2026")
    older_10k = _fm("NVDA", "10-K", date(2025, 2, 21), "ACC-10K-2025")
    recent_10q = _fm("NVDA", "10-Q", date(2026, 4, 30), "ACC-10Q-Q1")
    proxy = _fm("NVDA", "DEF 14A", date(2026, 3, 15), "ACC-DEF14A")
    form4 = _fm("NVDA", "4", date(2026, 3, 4), "ACC-FORM4")
    eightk = _fm("NVDA", "8-K", date(2026, 4, 1), "ACC-8K")
    s8 = _fm("NVDA", "S-8", date(2026, 4, 2), "ACC-S8")          # low-signal admin (P4)
    g13 = _fm("NVDA", "SC 13G", date(2026, 4, 3), "ACC-13G")     # low-signal admin (P4)
    if form == "10-K":
        return [recent_10k, older_10k][:limit] if limit else [recent_10k, older_10k]
    if form == "10-Q":
        return [recent_10q][:limit] if limit else [recent_10q]
    if form == "DEF 14A":
        return [proxy][:limit] if limit else [proxy]
    if form == "4":
        return [form4][:limit] if limit else [form4]
    if since_days == 90:
        # 90-day sweep: overlaps (recent_10k/10q) + 8-K + Form 4 + admin noise.
        return [recent_10q, recent_10k, eightk, form4, s8, g13]
    return []


def test_cmd_index_eval_profile_keeps_high_signal_and_form4_drops_admin(
    research_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default (eval) profile: core + proxy + 8-K + capped Form 4, deduped;
    administrative forms (S-8, 13G) deferred (issue #40)."""
    queue_root, _ = roots
    monkeypatch.setattr(research_mod, "list_recent_filings", _composite_fake_list)

    assert research_mod.cmd_index(_ns("NVDA")) == 0
    accessions = {
        json.loads(f.read_text())["accession"] for f in queue_root.glob("*.json")
    }
    assert accessions == {
        "ACC-10K-2026", "ACC-10K-2025", "ACC-10Q-Q1",  # core financials
        "ACC-DEF14A",                                   # proxy
        "ACC-8K",                                       # high-signal event (from sweep)
        "ACC-FORM4",                                    # capped recent insider Form 4
    }
    assert "ACC-S8" not in accessions   # admin deferred
    assert "ACC-13G" not in accessions


def test_cmd_index_full_profile_includes_low_signal(
    research_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--profile full` pulls everything in the window, incl. admin forms (#40)."""
    queue_root, _ = roots
    monkeypatch.setattr(research_mod, "list_recent_filings", _composite_fake_list)

    assert research_mod.cmd_index(_ns("NVDA", profile="full")) == 0
    accessions = {
        json.loads(f.read_text())["accession"] for f in queue_root.glob("*.json")
    }
    assert {"ACC-S8", "ACC-13G"} <= accessions  # admin now included
    assert {"ACC-10K-2026", "ACC-8K", "ACC-FORM4"} <= accessions


def test_cmd_index_no_matches_prints_no_data(
    research_mod,
    roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(research_mod, "list_recent_filings", lambda *a, **k: [])
    rc = research_mod.cmd_index(_ns("ZZZ", form="4"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "No filings found" in out
    queue_root, _ = roots
    assert list(queue_root.glob("*.json")) == []


def test_cmd_index_form_with_count_limits_results(
    research_mod,
    roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--count N caps the result set to the most-recent N filings."""
    queue_root, _ = roots
    fake = [
        _fm("NVDA", "10-K", date(2026, 2, 21), "ACC1"),
        _fm("NVDA", "10-K", date(2025, 2, 21), "ACC2"),
    ]

    captured: dict = {}

    def fake_list(ticker, **kwargs):
        captured.update(kwargs)
        return fake[: kwargs.get("limit") or len(fake)]

    monkeypatch.setattr(research_mod, "list_recent_filings", fake_list)
    rc = research_mod.cmd_index(_ns("NVDA", form="10-K", count=2))
    assert rc == 0
    assert captured["limit"] == 2
    # When count is set without days, days stays None (no window filter).
    assert captured["since_days"] is None


def test_cmd_index_passes_form_through(
    research_mod, roots: tuple[Path, Path]
) -> None:
    """Legacy compatibility: --form X --latest still enqueues a form-only request."""
    queue_root, _ = roots
    research_mod.cmd_index(_ns("AAPL", form="10-Q", latest=True))
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
    # Eval-readiness summary (issue #38): a 10-K makes the ticker eval-ready.
    assert "Eval readiness" in out
    assert "Ready to evaluate" in out


def test_cmd_status_not_eval_ready_without_annual_report(
    research_mod, roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, sec_root = roots
    status = TickerStatus(ticker="NVDA")
    status.merge_filing(
        FilingStatus(
            accession="acc-8k",
            form="8-K",
            filed="2026-05-01",
            indexed_at="2026-05-06T12:00:00+00:00",
            status="indexed",
        )
    )
    save_status(sec_root, status)

    research_mod.cmd_status(argparse.Namespace(ticker="NVDA"))
    out = capsys.readouterr().out
    assert "Not eval-ready yet" in out
    assert "annual report" in out


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


# ---- cmd_doctor (issue #55) ------------------------------------------------


def test_cmd_doctor_no_marker_is_ok(
    research_mod, roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    rc = research_mod.cmd_doctor(argparse.Namespace())
    out = capsys.readouterr().out
    assert "SEC indexer health" in out
    assert "no runtime marker" in out
    assert rc == 0  # missing marker isn't "stale"


def test_cmd_doctor_reports_stale(
    research_mod,
    roots: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_buffett_zo.indexer import runtime as runtime_mod
    from ai_buffett_zo.indexer import write_runtime_marker
    from ai_buffett_zo.observability import CodeVersion

    _, sec_root = roots
    write_runtime_marker(sec_root, CodeVersion("0.1.0", "oldoldold"))
    monkeypatch.setattr(runtime_mod, "code_version", lambda: CodeVersion("0.1.0", "newnewnew"))

    rc = research_mod.cmd_doctor(argparse.Namespace())
    out = capsys.readouterr().out
    assert "STALE" in out
    assert "Restart the `sec-indexer` service" in out
    assert rc == 1  # non-zero so callers can gate on it


# ---- cmd_reindex + index --force (issue #57) -------------------------------


def test_cmd_index_force_flag_enqueues_force(research_mod, roots: tuple[Path, Path]) -> None:
    from ai_buffett_zo.indexer import list_pending
    queue_root, _ = roots
    research_mod.cmd_index(_ns("NVDA", form="10-K", latest=True, force=True))
    assert list_pending(queue_root)[0].force is True


def test_cmd_reindex_enqueues_all_indexed(
    research_mod, roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    from ai_buffett_zo.indexer import list_pending
    queue_root, sec_root = roots
    save_tree(sec_root, _make_filing("NVDA", accession="acc-nvda"))
    save_tree(sec_root, _make_filing("AAPL", accession="acc-aapl"))
    rc = research_mod.cmd_reindex(argparse.Namespace(ticker=None, force=False))
    assert rc == 0
    pending = list_pending(queue_root)
    assert {p.ticker for p in pending} == {"NVDA", "AAPL"}
    assert all(p.force is False for p in pending)  # default: refresh-if-stale, not force
    assert "Re-index queued" in capsys.readouterr().out


def test_cmd_reindex_per_ticker(research_mod, roots: tuple[Path, Path]) -> None:
    from ai_buffett_zo.indexer import list_pending
    queue_root, sec_root = roots
    save_tree(sec_root, _make_filing("NVDA", accession="acc-nvda"))
    save_tree(sec_root, _make_filing("AAPL", accession="acc-aapl"))
    research_mod.cmd_reindex(argparse.Namespace(ticker="NVDA", force=False))
    assert [p.ticker for p in list_pending(queue_root)] == ["NVDA"]


def test_cmd_reindex_force_sets_flag(research_mod, roots: tuple[Path, Path]) -> None:
    from ai_buffett_zo.indexer import list_pending
    queue_root, sec_root = roots
    save_tree(sec_root, _make_filing("NVDA", accession="acc-nvda"))
    research_mod.cmd_reindex(argparse.Namespace(ticker="NVDA", force=True))
    assert list_pending(queue_root)[0].force is True


def test_cmd_reindex_no_indexed_filings(
    research_mod, roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    rc = research_mod.cmd_reindex(argparse.Namespace(ticker=None, force=False))
    assert rc == 0
    assert "No indexed filings" in capsys.readouterr().out
