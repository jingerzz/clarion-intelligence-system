"""Tests for skills/clarion-single-stock-eval/scripts/eval.py."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ai_buffett_zo.evaluation import Fundamentals
from ai_buffett_zo.regime import RegimeSnapshot
from ai_buffett_zo.secrag import (
    FilingMetadata,
    FilingTree,
    SectionNode,
    save_tree,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_PATH = REPO_ROOT / "skills" / "clarion-single-stock-eval" / "scripts" / "eval.py"


@pytest.fixture(scope="module")
def eval_mod():
    spec = importlib.util.spec_from_file_location("clarion_eval", EVAL_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["clarion_eval"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def sec_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sroot = tmp_path / "sec"
    monkeypatch.setenv("CLARION_SEC_ROOT", str(sroot))
    return sroot


def _fundamentals(ticker: str = "NVDA") -> Fundamentals:
    return Fundamentals(
        ticker=ticker,
        company=f"{ticker} Inc.",
        market_cap=3_000_000_000_000.0,
        trailing_pe=65.5,
        forward_pe=35.2,
        price_to_book=50.0,
        profit_margin=0.55,
        operating_margin=0.62,
        return_on_equity=1.20,
        return_on_assets=0.45,
        debt_to_equity=25.0,
        current_ratio=4.0,
        free_cash_flow=60_000_000_000.0,
        operating_cash_flow=65_000_000_000.0,
        dividend_yield=0.0003,
        week52_high=152.0,
        week52_low=80.0,
        last_close=140.0,
    )


def _regime(color: str = "orange", hurdle: float | None = 8.5) -> RegimeSnapshot:
    return RegimeSnapshot(
        asof=date(2026, 5, 6),
        color=color,  # type: ignore[arg-type]
        spy_ret_short=-0.025,
        tlt_ret_short=0.012,
        rsp_vs_spy_long=-0.060,
        spy_drawdown_from_high=-0.080,
        hurdle_rate_pct=hurdle,
        rationale="SPY -2.5% with TLT +1.2% — flight to safety",
        breadth_flag="broad",
    )


def _save_filing(
    sec_root: Path,
    ticker: str,
    sections: list[tuple[str, str]],
    *,
    form: str = "10-K",
) -> None:
    metadata = FilingMetadata(
        cik="0000000000",
        ticker=ticker,
        company=f"{ticker} Inc.",
        form=form,
        filed=date(2026, 2, 21),
        period=date(2026, 1, 26),
        accession=f"acc-{ticker}-{form}",
        primary_doc="x.htm",
        primary_doc_url=f"https://example/{ticker}.htm",
    )
    tree = FilingTree(
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
    save_tree(sec_root, tree)


def _patch_pipeline(
    eval_mod,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fundamentals: Fundamentals | None = None,
    regime: RegimeSnapshot | None = None,
) -> None:
    """Replace fetch_fundamentals + _maybe_regime in the script's import scope."""
    monkeypatch.setattr(
        eval_mod,
        "fetch_fundamentals",
        lambda t: (fundamentals or _fundamentals(t)),
    )
    monkeypatch.setattr(eval_mod, "_maybe_regime", lambda rf: regime)


def _args(
    ticker: str = "NVDA",
    *,
    rf: float | None = None,
    no_regime: bool = False,
    timing: bool = False,
):
    return argparse.Namespace(
        ticker=ticker, rf_rate_pct=rf, no_regime=no_regime, timing=timing
    )


# ---- run() ------------------------------------------------------------------


def test_run_unindexed_ticker_says_so(
    eval_mod, sec_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = eval_mod.run(_args("NVDA"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "NVDA" in out
    assert "No filings indexed" in out
    assert "clarion-sec-research index NVDA" in out


def test_run_renders_full_brief_when_indexed(
    eval_mod,
    sec_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _save_filing(
        sec_root,
        "NVDA",
        [
            ("business", "Competitive advantage from scale and software ecosystem."),
            ("mdna", "Operating margin expanded; capital allocation toward buybacks."),
            ("risk_factors", "Supply chain risk and regulation could impact gross margin."),
        ],
    )
    _patch_pipeline(eval_mod, monkeypatch, regime=_regime("orange", 8.5))

    rc = eval_mod.run(_args("NVDA", rf=4.5))
    assert rc == 0
    out = capsys.readouterr().out
    # All major sections present
    assert "Single-Stock Evaluation — NVDA" in out
    assert "## Market context" in out
    assert "ORANGE" in out
    assert "8.50%" in out
    assert "## Quality snapshot" in out
    assert "## Buffett lens" in out
    assert "Moat" in out
    assert "Management" in out
    assert "Financial trends" in out
    assert "Risk factors" in out
    assert "## Reading guide" in out
    # Citations and snippet presentation
    assert "Competitive advantage" in out or "ecosystem" in out  # at least one snippet
    assert "Clarion Intelligence System" in out  # footer signature


def test_run_with_no_regime_skips_market_context(
    eval_mod,
    sec_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _save_filing(sec_root, "NVDA", [("business", "Brief.")])
    _patch_pipeline(eval_mod, monkeypatch, regime=None)

    rc = eval_mod.run(_args("NVDA", no_regime=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "## Market context" not in out
    assert "ORANGE" not in out
    # Reading guide should NOT have the hurdle question (#5)
    assert "Hurdle clearance" not in out


def test_run_timing_flag_emits_summary_to_stderr(
    eval_mod,
    sec_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--timing prints a per-stage summary to stderr (issue #42); stdout stays clean."""
    _save_filing(sec_root, "NVDA", [("business", "Brief.")])
    _patch_pipeline(eval_mod, monkeypatch, regime=_regime("green", 7.0))

    rc = eval_mod.run(_args("NVDA", rf=4.5, timing=True))
    assert rc == 0
    captured = capsys.readouterr()

    # Timing goes to stderr, not stdout
    assert "Timing (NVDA):" in captured.err
    assert "SEC status" in captured.err
    assert "yfinance snapshot" in captured.err
    assert "regime check" in captured.err
    assert "Buffett lens search" in captured.err
    assert "Total:" in captured.err
    # stdout has the eval, not the timing block
    assert "Timing (NVDA):" not in captured.out


def test_run_without_timing_flag_emits_nothing_to_stderr(
    eval_mod,
    sec_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Default (no --timing): no timing noise anywhere."""
    _save_filing(sec_root, "NVDA", [("business", "Brief.")])
    _patch_pipeline(eval_mod, monkeypatch, regime=_regime("green", 7.0))

    eval_mod.run(_args("NVDA", rf=4.5, timing=False))
    captured = capsys.readouterr()
    assert "Timing" not in captured.err
    assert "Timing" not in captured.out


def test_run_with_rf_includes_hurdle(
    eval_mod,
    sec_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _save_filing(sec_root, "NVDA", [("business", "Brief.")])
    _patch_pipeline(eval_mod, monkeypatch, regime=_regime("orange", 8.5))
    eval_mod.run(_args("NVDA", rf=4.5))
    out = capsys.readouterr().out
    assert "Equity hurdle" in out
    assert "8.50%" in out
    assert "Hurdle clearance" in out  # reading guide question 5


def test_run_fundamentals_failure_returns_error_sentinel(
    eval_mod,
    sec_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _save_filing(sec_root, "NVDA", [("business", "Brief.")])

    def fail(_t: str):
        raise RuntimeError("yfinance offline")

    monkeypatch.setattr(eval_mod, "fetch_fundamentals", fail)
    monkeypatch.setattr(eval_mod, "_maybe_regime", lambda rf: None)

    rc = eval_mod.run(_args("NVDA"))
    assert rc == 1
    out = capsys.readouterr().out
    assert "EVAL_ERROR" in out
    assert "yfinance offline" in out


# ---- eval-readiness coverage note (issue #38) -------------------------------


def test_run_warns_on_partial_coverage_when_no_annual_report(
    eval_mod,
    sec_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Only an 8-K indexed → loud 'Partial coverage' note, eval still runs."""
    _save_filing(sec_root, "NVDA", [("body", "Material event disclosure.")], form="8-K")
    _patch_pipeline(eval_mod, monkeypatch, regime=None)

    rc = eval_mod.run(_args("NVDA", no_regime=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Partial coverage" in out
    assert "annual report" in out
    # The eval body still renders — partial coverage warns, doesn't block.
    assert "## Quality snapshot" in out


def test_run_quiet_coverage_note_when_annual_report_only(
    eval_mod,
    sec_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """10-K indexed but no 10-Q/proxy → quiet coverage line, no loud warning."""
    _save_filing(sec_root, "NVDA", [("business", "Brief.")], form="10-K")
    _patch_pipeline(eval_mod, monkeypatch, regime=None)

    rc = eval_mod.run(_args("NVDA", no_regime=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Partial coverage" not in out
    assert "Coverage:" in out
    assert "10-Q" in out  # names the still-queued gap


# ---- formatters -------------------------------------------------------------


def test_fmt_money_handles_billions_millions_and_small(eval_mod) -> None:
    assert eval_mod._fmt_money(None) == "—"
    assert eval_mod._fmt_money(3.5e12) == "$3500.00B"
    assert eval_mod._fmt_money(2.5e9) == "$2.50B"
    assert eval_mod._fmt_money(2.5e6) == "$2.5M"
    assert eval_mod._fmt_money(140.0) == "$140.00"


def test_fmt_pct(eval_mod) -> None:
    assert eval_mod._fmt_pct(None) == "—"
    assert eval_mod._fmt_pct(0.55) == "55.00%"
    assert eval_mod._fmt_pct(0.0003) == "0.03%"


def test_fmt_num(eval_mod) -> None:
    assert eval_mod._fmt_num(None) == "—"
    assert eval_mod._fmt_num(65.5) == "65.50"
