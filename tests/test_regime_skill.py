"""Tests for skills/clarion-regime-check/scripts/regime.py.

The yfinance fetch path (run()) is exercised by Phase A's end-to-end Zo test.
Here we cover format_regime_output — the pure formatting half of the script.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

from ai_buffett_zo.regime import RegimeSnapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
REGIME_PATH = REPO_ROOT / "skills" / "clarion-regime-check" / "scripts" / "regime.py"


@pytest.fixture(scope="module")
def regime_mod():
    spec = importlib.util.spec_from_file_location("clarion_regime", REGIME_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["clarion_regime"] = mod
    spec.loader.exec_module(mod)
    return mod


def _snap(
    color: str = "blue",
    *,
    hurdle: float | None = None,
    breadth_flag: str = "broad",
    rsp_vs_spy_long: float = -0.02,
    spy_ret_1d: float = -0.003,
    tlt_ret_1d: float = 0.002,
    big_blue_day: bool = False,
    capitulation: bool = False,
) -> RegimeSnapshot:
    return RegimeSnapshot(
        asof=date(2026, 5, 6),
        color=color,  # type: ignore[arg-type]
        spy_ret_short=-0.025,
        tlt_ret_short=0.012,
        rsp_vs_spy_long=rsp_vs_spy_long,
        spy_drawdown_from_high=-0.080,
        hurdle_rate_pct=hurdle,
        rationale="SPY -2.5% with TLT +1.2% — bond hedge working",
        breadth_flag=breadth_flag,  # type: ignore[arg-type]
        spy_ret_1d=spy_ret_1d,
        tlt_ret_1d=tlt_ret_1d,
        big_blue_day=big_blue_day,
        capitulation=capitulation,
    )


def test_format_regime_output_includes_color_and_date(regime_mod) -> None:
    out = regime_mod.format_regime_output(_snap("orange"))
    assert "ORANGE" in out
    assert "2026-05-06" in out


def test_format_regime_output_includes_signals_table(regime_mod) -> None:
    out = regime_mod.format_regime_output(_snap("orange"))
    assert "**Signals**" in out
    assert "SPY 20d return" in out
    assert "TLT 20d return" in out
    assert "RSP-SPY 60d spread" in out
    assert "SPY drawdown vs 252d high" in out


def test_format_regime_output_signals_use_signed_percent(regime_mod) -> None:
    out = regime_mod.format_regime_output(_snap("orange"))
    assert "-2.50%" in out
    assert "+1.20%" in out


def test_format_regime_output_omits_hurdle_when_not_set(regime_mod) -> None:
    out = regime_mod.format_regime_output(_snap("orange", hurdle=None))
    assert "Equity hurdle rate" not in out
    assert "Hurdle" not in out or "hurdle" not in out.lower().split("**hurdle")[0] if "**hurdle" in out.lower() else True


def test_format_regime_output_includes_hurdle_when_set(regime_mod) -> None:
    out = regime_mod.format_regime_output(_snap("orange", hurdle=8.5))
    assert "**Equity hurdle rate**" in out
    assert "8.50%" in out
    assert "regime premium" in out


def test_format_regime_output_rationale_present(regime_mod) -> None:
    snap = _snap("red")
    snap_with_rationale = RegimeSnapshot(
        asof=snap.asof,
        color="red",
        spy_ret_short=snap.spy_ret_short,
        tlt_ret_short=snap.tlt_ret_short,
        rsp_vs_spy_long=snap.rsp_vs_spy_long,
        spy_drawdown_from_high=snap.spy_drawdown_from_high,
        hurdle_rate_pct=snap.hurdle_rate_pct,
        rationale="correlation breakdown — SPY -7%, TLT -3%",
        breadth_flag=snap.breadth_flag,
    )
    out = regime_mod.format_regime_output(snap_with_rationale)
    assert "correlation breakdown" in out


def test_format_regime_output_shows_1d_returns_in_signals_table(regime_mod) -> None:
    out = regime_mod.format_regime_output(_snap("blue", spy_ret_1d=-0.012, tlt_ret_1d=0.015))
    assert "SPY 1d return" in out
    assert "TLT 1d return" in out
    assert "-1.20%" in out
    assert "+1.50%" in out


def test_format_regime_output_callout_when_big_blue_day_fires(regime_mod) -> None:
    out = regime_mod.format_regime_output(
        _snap("blue", spy_ret_1d=-0.012, tlt_ret_1d=0.015, big_blue_day=True)
    )
    assert "Big-Blue-Day flag fired" in out
    assert "actionable window" in out
    assert "1-2 trading day" in out


def test_format_regime_output_callout_when_capitulation_fires(regime_mod) -> None:
    out = regime_mod.format_regime_output(
        _snap("red", spy_ret_1d=-0.015, tlt_ret_1d=-0.005, capitulation=True)
    )
    assert "Capitulation flag fired" in out
    assert "above-average volume" in out
    assert "1-2 trading day" in out


def test_format_regime_output_no_callouts_when_flags_quiet(regime_mod) -> None:
    out = regime_mod.format_regime_output(
        _snap("green", spy_ret_1d=0.002, tlt_ret_1d=0.001)
    )
    assert "Big-Blue-Day flag fired" not in out
    assert "Capitulation flag fired" not in out


def test_format_regime_output_shows_breadth_in_signals_table(regime_mod) -> None:
    out = regime_mod.format_regime_output(_snap("green", breadth_flag="broad"))
    assert "Breadth" in out
    assert "broad" in out


def test_format_regime_output_callout_when_breadth_narrow(regime_mod) -> None:
    out = regime_mod.format_regime_output(
        _snap("green", breadth_flag="narrow", rsp_vs_spy_long=-0.08)
    )
    assert "narrow leadership" in out.lower()
    assert "does not change the color" in out


def test_format_regime_output_no_breadth_callout_when_broad(regime_mod) -> None:
    out = regime_mod.format_regime_output(_snap("green", breadth_flag="broad"))
    assert "narrow leadership" not in out.lower()


def test_format_regime_output_has_footer_with_signature(regime_mod) -> None:
    out = regime_mod.format_regime_output(_snap("green", hurdle=7.5))
    assert "Clarion Intelligence System" in out
    assert "UTC" in out
