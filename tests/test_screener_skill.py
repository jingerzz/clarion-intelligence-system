"""Tests for skills/clarion-value-screener/scripts/screen.py."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest

from ai_buffett_zo.evaluation import Fundamentals
from ai_buffett_zo.regime import RegimeSnapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "skills" / "clarion-value-screener" / "scripts" / "screen.py"


@pytest.fixture(scope="module")
def screen_mod():
    spec = importlib.util.spec_from_file_location("clarion_screen", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["clarion_screen"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def wl_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "watchlists"
    p.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLARION_WATCHLIST_ROOT", str(p))
    return p


def _regime(color: str = "orange") -> RegimeSnapshot:
    return RegimeSnapshot(
        asof=date(2026, 5, 7),
        color=color,  # type: ignore[arg-type]
        spy_ret_short=-0.025,
        tlt_ret_short=0.012,
        rsp_vs_spy_long=-0.060,
        spy_drawdown_from_high=-0.080,
        hurdle_rate_pct=None,
        rationale="rationale",
    )


def _fundamentals(ticker: str, **overrides) -> Fundamentals:
    base = {
        "ticker": ticker,
        "company": f"{ticker} Inc.",
        "market_cap": 100e9,
        "trailing_pe": 14.0,
        "forward_pe": 12.0,
        "price_to_book": 5.0,
        "profit_margin": 0.20,
        "operating_margin": 0.30,
        "return_on_equity": 0.25,
        "return_on_assets": 0.15,
        "debt_to_equity": 30.0,  # yfinance reports as percent (30 = 0.30 ratio)
        "current_ratio": 2.0,
        "free_cash_flow": 8e9,
        "operating_cash_flow": 9e9,
        "dividend_yield": 0.01,
        "week52_high": 200.0,
        "week52_low": 100.0,
        "last_close": 150.0,
    }
    base.update(overrides)
    return Fundamentals(**base)


def _args(
    *,
    tickers: str | None = None,
    input_path: str | None = None,
    rf_rate_pct: float | None = None,
    sp500_cape: float | None = None,
    universe: str = "S&P 500",
    top_size: int = 10,
    notes: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        tickers=tickers,
        input=input_path,
        screen_date=None,
        rf_rate_pct=rf_rate_pct,
        sp500_cape=sp500_cape,
        sp500_trailing_pe=None,
        implied_return_low_pct=None,
        implied_return_high_pct=None,
        universe=universe,
        notes=notes,
        top_size=top_size,
    )


# ---- error paths ------------------------------------------------------------


def test_run_errors_when_no_inputs(
    screen_mod, wl_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = screen_mod.run(_args())
    assert rc == 1
    assert "SCREEN_ERROR" in capsys.readouterr().out


def test_run_errors_when_input_file_missing(
    screen_mod, wl_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = screen_mod.run(_args(input_path="/tmp/does-not-exist.json"))
    assert rc == 1
    assert "input file not found" in capsys.readouterr().out


def test_run_errors_when_input_json_malformed(
    screen_mod, wl_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    rc = screen_mod.run(_args(input_path=str(bad)))
    assert rc == 1
    assert "input JSON malformed" in capsys.readouterr().out


def test_run_errors_when_regime_unavailable(
    screen_mod, wl_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(screen_mod, "_resolve_regime", lambda: None)
    monkeypatch.setattr(screen_mod, "_resolve_rf", lambda args: 4.45)
    monkeypatch.setattr(screen_mod, "_candidates_from_tickers", lambda ts: [])

    rc = screen_mod.run(_args(tickers="NVDA"))
    assert rc == 1
    assert "regime unavailable" in capsys.readouterr().out


# ---- happy paths ------------------------------------------------------------


def test_run_tickers_mode_writes_watchlist(
    screen_mod, wl_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(screen_mod, "_resolve_regime", lambda: _regime("orange"))
    monkeypatch.setattr(screen_mod, "_resolve_rf", lambda args: 4.45)
    monkeypatch.setattr(
        screen_mod,
        "fetch_fundamentals",
        lambda t: _fundamentals(t),
    )
    monkeypatch.setattr(screen_mod, "_sector_for", lambda t: "Tech")

    rc = screen_mod.run(_args(tickers="NVDA,AAPL,ADBE"))
    assert rc == 0

    files = list(wl_root.glob("sp500-screen-*.md"))
    assert len(files) == 1
    content = files[0].read_text()
    assert "S&P 500 Value Screen" in content
    assert "ORANGE" in content
    assert "NVDA" in content and "AAPL" in content and "ADBE" in content
    out = capsys.readouterr().out
    assert "Wrote " in out


def test_run_input_mode_uses_json_context_and_candidates(
    screen_mod, wl_root: Path, tmp_path: Path
) -> None:
    payload = {
        "screen_date": "2026-05-07",
        "context": {
            "regime_color": "orange",
            "rf_rate_pct": 4.45,
            "hurdle_rate_pct": 10.45,
            "sp500_cape": 35.2,
            "universe": "S&P 500",
            "notes": "test run",
        },
        "candidates": [
            {
                "ticker": "NVDA",
                "company": "NVIDIA",
                "sector": "Tech",
                "pe": 18.0,
                "pfcf": 14.0,
                "roe": 0.25,
                "roic": 0.20,
                "op_margin": 0.30,
                "profit_margin": 0.22,
                "de": 0.30,
                "insider_pct": 2.0,
                "market_cap": 3e12,
                "price": 140.0,
            },
        ],
    }
    f = tmp_path / "screen.json"
    f.write_text(json.dumps(payload))

    rc = screen_mod.run(_args(input_path=str(f)))
    assert rc == 0
    files = list(wl_root.glob("sp500-screen-2026-05-07.md"))
    assert len(files) == 1
    content = files[0].read_text()
    assert "test run" in content  # notes propagated
    assert "10.45%" in content


def test_run_input_mode_no_candidates_errors(
    screen_mod, wl_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "empty.json"
    f.write_text(json.dumps({"context": {}, "candidates": []}))
    rc = screen_mod.run(_args(input_path=str(f)))
    assert rc == 1
    assert "no candidates" in capsys.readouterr().out.lower()


def test_run_summary_lists_top_after_cap(
    screen_mod, wl_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(screen_mod, "_resolve_regime", lambda: _regime("orange"))
    monkeypatch.setattr(screen_mod, "_resolve_rf", lambda args: 4.45)
    monkeypatch.setattr(screen_mod, "fetch_fundamentals", lambda t: _fundamentals(t))
    monkeypatch.setattr(screen_mod, "_sector_for", lambda t: "Tech")

    screen_mod.run(_args(tickers="NVDA,AAPL"))
    out = capsys.readouterr().out
    assert "Top" in out
    assert "NVDA" in out
    assert "AAPL" in out
    assert "Next steps" in out
    assert "clarion-single-stock-eval" in out


# ---- helpers ---------------------------------------------------------------


def test_candidates_from_json_handles_missing_fields(screen_mod) -> None:
    blob = {"candidates": [{"ticker": "X"}]}
    candidates = screen_mod._candidates_from_json(blob)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.ticker == "X"
    assert c.pe is None
    assert c.sector == "Unknown"


def test_candidates_from_json_skips_rows_without_ticker(screen_mod) -> None:
    blob = {"candidates": [{"company": "no ticker"}, {"ticker": "X"}]}
    candidates = screen_mod._candidates_from_json(blob)
    assert len(candidates) == 1


def test_candidates_from_tickers_normalizes_de_from_yfinance_percent(
    screen_mod, monkeypatch: pytest.MonkeyPatch
) -> None:
    """yfinance reports debt_to_equity as a percent (30 = 0.30 ratio)."""
    monkeypatch.setattr(screen_mod, "fetch_fundamentals", lambda t: _fundamentals(t, debt_to_equity=30.0))
    monkeypatch.setattr(screen_mod, "_sector_for", lambda t: "Tech")
    candidates = screen_mod._candidates_from_tickers(["NVDA"])
    assert candidates[0].de == 0.30


def test_candidates_from_tickers_computes_pfcf(
    screen_mod, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        screen_mod,
        "fetch_fundamentals",
        lambda t: _fundamentals(t, market_cap=100e9, free_cash_flow=10e9),
    )
    monkeypatch.setattr(screen_mod, "_sector_for", lambda t: "Tech")
    candidates = screen_mod._candidates_from_tickers(["NVDA"])
    assert candidates[0].pfcf == 10.0


def test_candidates_from_tickers_skips_failed_fetch(
    screen_mod, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(_t):
        raise RuntimeError("yfinance offline")

    monkeypatch.setattr(screen_mod, "fetch_fundamentals", fail)
    monkeypatch.setattr(screen_mod, "_sector_for", lambda t: "Tech")
    candidates = screen_mod._candidates_from_tickers(["NVDA"])
    assert candidates == []
    assert "yfinance fetch failed" in capsys.readouterr().out
