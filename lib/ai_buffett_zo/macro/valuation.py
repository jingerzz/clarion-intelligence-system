"""S&P 500 valuation framework.

Source: docs/ALLOCATION-POLICY.md → Expected-Return Framework.

The historical CAPE → 10-year forward return mapping is a coarse-grained base
rate, not a precise model. Use the Shiller CAPE as the primary lookup; the
trailing P/E is a secondary cross-check.

`decide_allocation` maps (implied return, rf rate, hurdle) → 5-tier verdict
plus equity/T-bill split for the Value bucket.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# (low_pe_inclusive, high_pe_exclusive, return_low_pct, return_high_pct, confidence)
_PE_LOOKUP_TABLE: list[tuple[float, float, float, float, str]] = [
    (-float("inf"), 10.0, 12.0, 16.0, "high"),
    (10.0, 15.0, 8.0, 12.0, "high"),
    (15.0, 20.0, 5.0, 8.0, "moderate"),
    (20.0, 25.0, 2.0, 5.0, "moderate"),
    (25.0, 30.0, 0.0, 3.0, "moderate"),
    (30.0, float("inf"), -2.0, 0.0, "low"),
]


Verdict = Literal[
    "STRONG EQUITY",
    "LEAN EQUITY",
    "NEUTRAL",
    "LEAN T-BILLS",
    "MAXIMUM T-BILLS",
]


@dataclass(frozen=True)
class ImpliedReturn:
    """Historical 10-year forward return implied by a given P/E."""

    pe_used: float
    return_low_pct: float
    return_high_pct: float
    confidence: str

    @property
    def midpoint_pct(self) -> float:
        return (self.return_low_pct + self.return_high_pct) / 2


@dataclass(frozen=True)
class AllocationDecision:
    """5-tier verdict + equity/T-bill split + plain-language rationale."""

    verdict: Verdict
    equity_low: int
    equity_high: int
    rationale: str


def implied_return_from_pe(pe: float) -> ImpliedReturn:
    """Look up the historical 10-year forward return range for a given P/E."""
    for lo, hi, rl, rh, conf in _PE_LOOKUP_TABLE:
        if lo <= pe < hi:
            return ImpliedReturn(
                pe_used=pe,
                return_low_pct=rl,
                return_high_pct=rh,
                confidence=conf,
            )
    return ImpliedReturn(pe_used=pe, return_low_pct=0.0, return_high_pct=0.0, confidence="low")


def decide_allocation(
    *,
    implied_return_mid_pct: float,
    rf_rate_pct: float,
    hurdle_rate_pct: float,
    danger_state: bool = False,
) -> AllocationDecision:
    """Map (implied return, rf, hurdle) to a 5-tier Value-bucket allocation.

    Per docs/ALLOCATION-POLICY.md:

        Spread vs hurdle              Verdict           Equity %
        > Hurdle + 3%                 STRONG EQUITY     80-100%
        > Hurdle                      LEAN EQUITY       60-80%
        Within ±1% of Hurdle          NEUTRAL           40-60%
        < Hurdle                      LEAN T-BILLS      20-40%
        < rf rate                     MAXIMUM T-BILLS   0-20%

    Hard rule: `danger_state=True` forces MAXIMUM T-BILLS regardless of math.
    """
    if danger_state:
        return AllocationDecision(
            verdict="MAXIMUM T-BILLS",
            equity_low=0,
            equity_high=20,
            rationale="DANGER regime — capital preservation overrides P/E math.",
        )
    if implied_return_mid_pct < rf_rate_pct:
        return AllocationDecision(
            verdict="MAXIMUM T-BILLS",
            equity_low=0,
            equity_high=20,
            rationale=(
                f"Implied equity return ({implied_return_mid_pct:.1f}%) is below the "
                f"risk-free rate ({rf_rate_pct:.2f}%). Equity risk for less than "
                f"risk-free return is a losing proposition."
            ),
        )

    # Spread first; bands resolve in this order so the ±1% NEUTRAL band can
    # claim its territory before the "above hurdle" general bucket.
    spread = implied_return_mid_pct - hurdle_rate_pct

    if spread > 3.0:
        return AllocationDecision(
            verdict="STRONG EQUITY",
            equity_low=80,
            equity_high=100,
            rationale=(
                f"Implied return ({implied_return_mid_pct:.1f}%) clears the hurdle "
                f"({hurdle_rate_pct:.2f}%) by more than 3 points. Lean fully into equities."
            ),
        )
    if abs(spread) <= 1.0:
        return AllocationDecision(
            verdict="NEUTRAL",
            equity_low=40,
            equity_high=60,
            rationale=(
                f"Implied return ({implied_return_mid_pct:.1f}%) is within ±1 point of "
                f"the hurdle ({hurdle_rate_pct:.2f}%). Balanced posture."
            ),
        )
    if spread > 0:
        return AllocationDecision(
            verdict="LEAN EQUITY",
            equity_low=60,
            equity_high=80,
            rationale=(
                f"Implied return ({implied_return_mid_pct:.1f}%) is 1–3 points above the "
                f"hurdle ({hurdle_rate_pct:.2f}%). Tilt toward equities."
            ),
        )
    return AllocationDecision(
        verdict="LEAN T-BILLS",
        equity_low=20,
        equity_high=40,
        rationale=(
            f"Implied return ({implied_return_mid_pct:.1f}%) is more than 1 point below "
            f"the hurdle ({hurdle_rate_pct:.2f}%) but above the risk-free rate "
            f"({rf_rate_pct:.2f}%). Tilt toward T-bills."
        ),
    )
