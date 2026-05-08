"""Typed model of the value screener's inputs and outputs.

A screen has three layers:

  1. Context — regime, hurdle rate, screening stance (set by current macro)
  2. Candidate list — fundamentals + sector + insider activity per ticker
                      (Stage 1 input; usually prepared by the chat agent via
                      WebFetch over a screener site)
  3. Scored result — composite score per candidate, ranked, with sector-cap
                     decisions surfaced

The lib is deterministic: given (Context, candidates), it produces the same
ScreenResult every time. The chat agent does the data gathering; the lib
does the math and the output rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

ScreeningStance = Literal["Standard", "Tightened", "Maximum Value Only"]


@dataclass(frozen=True)
class ScreenContext:
    """The macro frame the screen runs against."""

    screen_date: date
    regime_color: str                  # green | blue | orange | red | danger
    danger_state: bool = False
    rf_rate_pct: float | None = None
    hurdle_rate_pct: float | None = None
    sp500_cape: float | None = None
    sp500_trailing_pe: float | None = None
    implied_return_low_pct: float | None = None
    implied_return_high_pct: float | None = None
    universe: str = "S&P 500"
    notes: str = ""

    @property
    def stance(self) -> ScreeningStance:
        """Map regime + danger to the screening stance."""
        if self.danger_state or self.regime_color in ("red", "danger"):
            return "Maximum Value Only"
        if self.regime_color == "orange":
            return "Tightened"
        return "Standard"


@dataclass(frozen=True)
class Candidate:
    """One row of the Stage 1 candidate list.

    Fundamentals are decimals where natural — ROE 0.20 = 20%. Insider activity
    is a percent number representing net 90-day insider buying as a % of
    insider holdings (positive = net buying, negative = net selling).

    Any field can be None when the screener site didn't return it; the scoring
    function tolerates None and reduces the weight contribution accordingly.
    """

    ticker: str
    company: str | None = None
    sector: str = "Unknown"
    pe: float | None = None
    pfcf: float | None = None
    roe: float | None = None              # decimal, 0.20 = 20%
    roic: float | None = None             # decimal
    op_margin: float | None = None        # decimal
    profit_margin: float | None = None    # decimal
    de: float | None = None               # debt/equity ratio
    insider_pct: float | None = None      # signed %; +6.7 = net buying
    market_cap: float | None = None       # USD
    price: float | None = None            # USD


@dataclass
class ScoredCandidate:
    """Candidate + composite score + per-component scores (for transparency)."""

    candidate: Candidate
    composite: float                       # 0-100
    component_scores: dict[str, float] = field(default_factory=dict)
    contributing_weight: float = 100.0     # what % of the formula's weight had data
    passed_threshold: bool = True


@dataclass(frozen=True)
class SectorCapResult:
    """Outcome of applying the sector cap to a ranked list."""

    top: list[ScoredCandidate]                  # final top-N after cap
    displaced: list[tuple[ScoredCandidate, str]]  # (candidate, reason) pairs
    sectors_relaxed: bool = False               # true if the <4-sectors exception fired
