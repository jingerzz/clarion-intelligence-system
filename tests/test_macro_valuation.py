"""Tests for ai_buffett_zo.macro.valuation."""

from __future__ import annotations

import pytest

from ai_buffett_zo.macro import (
    AllocationDecision,
    ImpliedReturn,
    decide_allocation,
    implied_return_from_pe,
)


# ---- implied_return_from_pe ------------------------------------------------


@pytest.mark.parametrize(
    ("pe", "expected_low", "expected_high", "expected_confidence"),
    [
        (8.0, 12.0, 16.0, "high"),    # < 10
        (10.0, 8.0, 12.0, "high"),    # boundary inclusive lower
        (12.5, 8.0, 12.0, "high"),    # 10-15
        (17.0, 5.0, 8.0, "moderate"), # 15-20
        (22.0, 2.0, 5.0, "moderate"), # 20-25
        (27.0, 0.0, 3.0, "moderate"), # 25-30
        (35.0, -2.0, 0.0, "low"),     # > 30
    ],
)
def test_implied_return_table_lookup(
    pe: float, expected_low: float, expected_high: float, expected_confidence: str
) -> None:
    r = implied_return_from_pe(pe)
    assert isinstance(r, ImpliedReturn)
    assert r.pe_used == pe
    assert r.return_low_pct == expected_low
    assert r.return_high_pct == expected_high
    assert r.confidence == expected_confidence


def test_implied_return_midpoint() -> None:
    r = implied_return_from_pe(17.0)
    assert r.midpoint_pct == 6.5
    r2 = implied_return_from_pe(35.0)
    assert r2.midpoint_pct == -1.0


def test_implied_return_table_boundaries_are_inclusive_lower() -> None:
    """A PE of exactly 10.0 belongs to the [10, 15) bucket, not [<10)."""
    assert implied_return_from_pe(10.0).return_low_pct == 8.0
    assert implied_return_from_pe(15.0).return_low_pct == 5.0
    assert implied_return_from_pe(30.0).return_low_pct == -2.0


# ---- decide_allocation ----------------------------------------------------


def test_danger_overrides_everything() -> None:
    d = decide_allocation(
        implied_return_mid_pct=20.0,  # absurdly high
        rf_rate_pct=4.5,
        hurdle_rate_pct=8.5,
        danger_state=True,
    )
    assert d.verdict == "MAXIMUM T-BILLS"
    assert d.equity_low == 0
    assert d.equity_high == 20
    assert "danger" in d.rationale.lower()


def test_implied_below_rf_forces_max_t_bills() -> None:
    d = decide_allocation(
        implied_return_mid_pct=2.0,
        rf_rate_pct=4.5,
        hurdle_rate_pct=10.5,
    )
    assert d.verdict == "MAXIMUM T-BILLS"
    assert "below the risk-free rate" in d.rationale.lower()


def test_strong_equity_when_spread_above_hurdle_plus_3() -> None:
    d = decide_allocation(
        implied_return_mid_pct=14.0,  # 14 - 10.5 = 3.5, above +3 cushion
        rf_rate_pct=4.5,
        hurdle_rate_pct=10.5,
    )
    assert d.verdict == "STRONG EQUITY"
    assert d.equity_low == 80
    assert d.equity_high == 100


def test_lean_equity_when_above_hurdle_but_within_3() -> None:
    d = decide_allocation(
        implied_return_mid_pct=12.0,  # 12 - 10.5 = 1.5, between hurdle and hurdle+3
        rf_rate_pct=4.5,
        hurdle_rate_pct=10.5,
    )
    assert d.verdict == "LEAN EQUITY"
    assert d.equity_low == 60
    assert d.equity_high == 80


def test_neutral_within_1_pct_of_hurdle() -> None:
    d = decide_allocation(
        implied_return_mid_pct=10.0,  # 0.5 below hurdle
        rf_rate_pct=4.5,
        hurdle_rate_pct=10.5,
    )
    assert d.verdict == "NEUTRAL"
    assert d.equity_low == 40
    assert d.equity_high == 60


def test_lean_t_bills_when_below_hurdle_but_above_rf() -> None:
    d = decide_allocation(
        implied_return_mid_pct=7.0,  # below hurdle 10.5 by >1, above rf 4.5
        rf_rate_pct=4.5,
        hurdle_rate_pct=10.5,
    )
    assert d.verdict == "LEAN T-BILLS"
    assert d.equity_low == 20
    assert d.equity_high == 40


def test_neutral_just_above_hurdle_within_one_pct() -> None:
    """Just above the hurdle by 0.5% — should still be NEUTRAL (within ±1%)."""
    d = decide_allocation(
        implied_return_mid_pct=11.0,
        rf_rate_pct=4.5,
        hurdle_rate_pct=10.5,
    )
    assert d.verdict == "NEUTRAL"


def test_decision_dataclass_shape() -> None:
    d = decide_allocation(
        implied_return_mid_pct=12.0,
        rf_rate_pct=4.5,
        hurdle_rate_pct=10.5,
    )
    assert isinstance(d, AllocationDecision)
    assert d.equity_low + d.equity_high <= 200
    assert d.equity_low <= d.equity_high
    assert d.rationale
