"""Tests for skills/clarion-expected-return-calc/scripts/expected_return.py."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

from ai_buffett_zo.macro import TreasuryYield
from ai_buffett_zo.regime import RegimeSnapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    REPO_ROOT / "skills" / "clarion-expected-return-calc" / "scripts" / "expected_return.py"
)


@pytest.fixture(scope="module")
def er_mod():
    spec = importlib.util.spec_from_file_location("clarion_er", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["clarion_er"] = mod
    spec.loader.exec_module(mod)
    return mod


def _regime(color: str = "orange") -> RegimeSnapshot:
    return RegimeSnapshot(
        asof=date(2026, 5, 6),
        color=color,  # type: ignore[arg-type]
        spy_ret_short=-0.025,
        tlt_ret_short=0.012,
        rsp_vs_spy_long=-0.060,
        spy_drawdown_from_high=-0.080,
        hurdle_rate_pct=None,
        rationale="SPY -2.5% with TLT +1.2% — flight to safety",
    )


def _args(
    *,
    cape: float | None = 35.0,
    trailing_pe: float | None = None,
    forward_pe: float | None = None,
    rf_rate_pct: float | None = None,
    ten_year_yield_pct: float | None = None,
    no_fetch_rf: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        cape=cape,
        trailing_pe=trailing_pe,
        forward_pe=forward_pe,
        rf_rate_pct=rf_rate_pct,
        ten_year_yield_pct=ten_year_yield_pct,
        no_fetch_rf=no_fetch_rf,
    )


def _patch_full_pipeline(
    er_mod,
    monkeypatch: pytest.MonkeyPatch,
    *,
    rf_rate_pct: float = 4.45,
    rf_source: str = "Treasury.gov 3-mo (asof 2026-05-06)",
    regime_color: str = "orange",
) -> None:
    monkeypatch.setattr(er_mod, "_resolve_rf", lambda args: (rf_rate_pct, rf_source))
    monkeypatch.setattr(er_mod, "_resolve_regime", lambda: _regime(regime_color))


# ---- _resolve_rf -----------------------------------------------------------


def test_resolve_rf_user_supplied_wins(er_mod) -> None:
    rate, source = er_mod._resolve_rf(_args(rf_rate_pct=4.20))
    assert rate == 4.20
    assert source == "user-supplied"


def test_resolve_rf_uses_treasury_when_available(
    er_mod, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        er_mod,
        "fetch_3mo_yield",
        lambda: TreasuryYield(asof=date(2026, 5, 6), tenor="3 Mo", rate_pct=4.45),
    )
    rate, source = er_mod._resolve_rf(_args(rf_rate_pct=None))
    assert rate == 4.45
    assert "Treasury.gov" in source
    assert "2026-05-06" in source


def test_resolve_rf_no_fetch_skips_treasury(
    er_mod, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--no-fetch-rf without --rf-rate-pct should fall through to config / unresolved."""
    calls = []
    monkeypatch.setattr(er_mod, "fetch_3mo_yield", lambda: calls.append(1) or None)
    monkeypatch.setattr(er_mod, "_config_rf", lambda: None)
    rate, source = er_mod._resolve_rf(_args(no_fetch_rf=True))
    assert rate is None
    assert source == "unresolved"
    assert calls == []  # never called


def test_resolve_rf_falls_back_to_config(
    er_mod, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(er_mod, "fetch_3mo_yield", lambda: None)
    monkeypatch.setattr(er_mod, "_config_rf", lambda: 4.10)
    rate, source = er_mod._resolve_rf(_args(rf_rate_pct=None))
    assert rate == 4.10
    assert "config.json" in source


# ---- run() error paths -----------------------------------------------------


def test_run_errors_when_rf_unresolved(
    er_mod, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(er_mod, "_resolve_rf", lambda args: (None, "unresolved"))
    rc = er_mod.run(_args(cape=35.0))
    assert rc == 1
    out = capsys.readouterr().out
    assert "EXPECTED_RETURN_ERROR" in out
    assert "risk-free rate" in out


def test_run_errors_when_regime_unavailable(
    er_mod, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(er_mod, "_resolve_rf", lambda args: (4.45, "user-supplied"))
    monkeypatch.setattr(er_mod, "_resolve_regime", lambda: None)
    rc = er_mod.run(_args(cape=35.0))
    assert rc == 1
    out = capsys.readouterr().out
    assert "EXPECTED_RETURN_ERROR" in out
    assert "regime" in out


def test_run_errors_when_cape_missing(
    er_mod, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_full_pipeline(er_mod, monkeypatch)
    rc = er_mod.run(_args(cape=None))
    assert rc == 1
    out = capsys.readouterr().out
    assert "--cape is required" in out


# ---- run() happy paths -----------------------------------------------------


def test_run_orange_regime_high_cape_renders_strong_t_bills(
    er_mod, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CAPE 35 in ORANGE: implied return midpoint = -1%, rf = 4.45 → MAXIMUM T-BILLS."""
    _patch_full_pipeline(er_mod, monkeypatch, regime_color="orange")
    rc = er_mod.run(_args(cape=35.0))
    assert rc == 0
    out = capsys.readouterr().out
    # All expected sections
    assert "## The Numbers" in out
    assert "## The Math" in out
    assert "## The Verdict" in out
    assert "## Recommended Value Bucket Split" in out
    assert "## Context" in out
    # Numbers in math
    assert "4.45%" in out
    assert "10.45%" in out  # hurdle = 4.45 + 6.0
    # Verdict
    assert "MAXIMUM T-BILLS" in out
    assert "0-20%" in out  # equity split


def test_run_low_cape_in_orange_renders_strong_equity(
    er_mod, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CAPE 12 in ORANGE: implied 8-12% mid 10%, rf 4.45, hurdle 10.45 → NEUTRAL."""
    _patch_full_pipeline(er_mod, monkeypatch, regime_color="orange")
    rc = er_mod.run(_args(cape=12.0))
    assert rc == 0
    out = capsys.readouterr().out
    # Implied 10% within ±1 of hurdle 10.45 → NEUTRAL
    assert "NEUTRAL" in out
    assert "40-60%" in out


def test_run_danger_regime_forces_max_t_bills_regardless_of_cape(
    er_mod, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_full_pipeline(er_mod, monkeypatch, regime_color="danger")
    rc = er_mod.run(_args(cape=8.0))  # would otherwise imply 12-16%
    assert rc == 0
    out = capsys.readouterr().out
    assert "MAXIMUM T-BILLS" in out
    assert "DANGER" in out


def test_run_includes_divergence_warning(
    er_mod, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_full_pipeline(er_mod, monkeypatch)
    er_mod.run(_args(cape=35.0, trailing_pe=22.0))  # diverge by 13
    out = capsys.readouterr().out
    assert "diverge" in out.lower()


def test_run_no_divergence_warning_when_close(
    er_mod, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_full_pipeline(er_mod, monkeypatch)
    er_mod.run(_args(cape=35.0, trailing_pe=33.0))  # diverge by 2
    out = capsys.readouterr().out
    assert "diverge" not in out.lower()


def test_run_optional_inputs_render_when_supplied(
    er_mod, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_full_pipeline(er_mod, monkeypatch)
    er_mod.run(
        _args(
            cape=35.0,
            trailing_pe=28.0,
            forward_pe=22.0,
            ten_year_yield_pct=4.85,
        )
    )
    out = capsys.readouterr().out
    assert "28.00" in out  # trailing
    assert "22.00" in out  # forward
    assert "4.85%" in out  # 10-yr


def test_run_context_section_lists_regime_scenarios(
    er_mod, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_full_pipeline(er_mod, monkeypatch, regime_color="orange")
    er_mod.run(_args(cape=20.0))
    out = capsys.readouterr().out
    # Orange → both green/blue and red scenarios
    assert "GREEN/BLUE" in out
    assert "RED" in out
    # 15% correction scenario always in
    assert "15% market correction" in out
