"""SPY/TLT/RSP color regime + equity hurdle rate.

Five colors capture the cross-asset risk environment:

    green   SPY up, TLT down                  classic risk-on / expansion
    blue    SPY up, TLT up                    "everything works"
    orange  SPY down + TLT up, OR narrow      flight to safety, or breadth flag
            breadth (RSP/SPY underperforms)
    red     SPY down, TLT also down           correlation breakdown
    danger  SPY drawdown ≤ -20% from 252d hi  max defense

Each color maps to (a) an allocation band per ai-buffett ALLOCATION-POLICY.md
and (b) an equity hurdle premium added to the risk-free rate. Worse regimes
demand a higher hurdle — we require more expected return before deploying.

This is a defensible v1 derived from documented SPY/TLT/RSP regime concepts,
not ported from any proprietary algorithm. Thresholds are parameterized for
backtesting.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from ai_buffett_zo.data import Bar

Color = Literal["green", "blue", "orange", "red", "danger"]

# Equity hurdle premium added to the risk-free rate. Higher in worse regimes.
# Values match the source allocation policy (docs/ALLOCATION-POLICY.md).
HURDLE_PREMIUM_PCT: dict[Color, float] = {
    "green": 4.0,
    "blue": 4.0,
    "orange": 6.0,
    "red": 8.0,
    "danger": 10.0,
}

DEFAULT_LOOKBACK_SHORT = 20  # ~1 trading month
DEFAULT_LOOKBACK_LONG = 60   # ~3 trading months
DEFAULT_DRAWDOWN_DANGER = -0.20
DEFAULT_BREADTH_NARROW = -0.05  # RSP - SPY 60d cumulative spread


@dataclass(frozen=True)
class RegimeSnapshot:
    asof: date
    color: Color
    spy_ret_short: float            # 20d cumulative return
    tlt_ret_short: float            # 20d cumulative return
    rsp_vs_spy_long: float          # 60d (RSP - SPY) cumulative return spread
    spy_drawdown_from_high: float   # negative or zero, vs. 252d high
    hurdle_rate_pct: float | None   # None if rf_rate_pct not supplied
    rationale: str                  # which rule fired and why


def snapshot(
    spy: Sequence[Bar],
    tlt: Sequence[Bar],
    rsp: Sequence[Bar],
    *,
    rf_rate_pct: float | None = None,
    asof: date | None = None,
    lookback_short: int = DEFAULT_LOOKBACK_SHORT,
    lookback_long: int = DEFAULT_LOOKBACK_LONG,
    drawdown_danger: float = DEFAULT_DRAWDOWN_DANGER,
    breadth_narrow: float = DEFAULT_BREADTH_NARROW,
) -> RegimeSnapshot:
    """Classify regime and compute the hurdle rate.

    rf_rate_pct: 1Y T-bill yield (caller supplies — we don't fetch macro data).
                 If None, hurdle_rate_pct is None.
    asof: defaults to the last SPY bar's date.

    Raises ValueError if any series has fewer than (lookback_long + 1) bars or
    if the RSP series is shorter than lookback_long + 1.
    """
    asof_date = asof or spy[-1].date

    spy_ret_short = _ret(spy, lookback_short)
    tlt_ret_short = _ret(tlt, lookback_short)
    spy_ret_long = _ret(spy, lookback_long)
    rsp_ret_long = _ret(rsp, lookback_long)
    rsp_vs_spy_long = rsp_ret_long - spy_ret_long
    drawdown = _drawdown_from_high(spy, lookback=252)

    color, rationale = _classify(
        spy_ret_short=spy_ret_short,
        tlt_ret_short=tlt_ret_short,
        rsp_vs_spy_long=rsp_vs_spy_long,
        drawdown=drawdown,
        lookback_long=lookback_long,
        drawdown_danger=drawdown_danger,
        breadth_narrow=breadth_narrow,
    )

    hurdle = (
        round(rf_rate_pct + HURDLE_PREMIUM_PCT[color], 2)
        if rf_rate_pct is not None
        else None
    )

    return RegimeSnapshot(
        asof=asof_date,
        color=color,
        spy_ret_short=spy_ret_short,
        tlt_ret_short=tlt_ret_short,
        rsp_vs_spy_long=rsp_vs_spy_long,
        spy_drawdown_from_high=drawdown,
        hurdle_rate_pct=hurdle,
        rationale=rationale,
    )


def _classify(
    *,
    spy_ret_short: float,
    tlt_ret_short: float,
    rsp_vs_spy_long: float,
    drawdown: float,
    lookback_long: int,
    drawdown_danger: float,
    breadth_narrow: float,
) -> tuple[Color, str]:
    """First-match decision tree. Order matters — severe states first."""
    if drawdown <= drawdown_danger:
        return "danger", (
            f"SPY drawdown {drawdown:+.1%} hits {drawdown_danger:+.0%} threshold"
        )
    if spy_ret_short < -0.05 and tlt_ret_short < 0:
        return "red", (
            f"SPY {spy_ret_short:+.1%} and TLT {tlt_ret_short:+.1%} both falling — "
            f"correlation breakdown / risk-off without bond support"
        )
    if spy_ret_short < 0 and tlt_ret_short > 0:
        return "orange", (
            f"SPY {spy_ret_short:+.1%} negative with TLT {tlt_ret_short:+.1%} positive — "
            f"flight to safety"
        )
    if rsp_vs_spy_long < breadth_narrow:
        return "orange", (
            f"RSP-SPY spread {rsp_vs_spy_long:+.1%} over {lookback_long}d — "
            f"narrow leadership / late-cycle concentration"
        )
    if spy_ret_short > 0 and tlt_ret_short > 0:
        return "blue", (
            f"SPY {spy_ret_short:+.1%} and TLT {tlt_ret_short:+.1%} both positive — "
            f"everything works; verify breadth before adding"
        )
    if spy_ret_short > 0 and tlt_ret_short < 0:
        return "green", (
            f"SPY {spy_ret_short:+.1%} up, TLT {tlt_ret_short:+.1%} down — "
            f"classic risk-on, expansion regime"
        )
    return "orange", (
        f"SPY {spy_ret_short:+.1%}, TLT {tlt_ret_short:+.1%} — "
        f"mixed/neutral, default conservative"
    )


def _ret(bars: Sequence[Bar], lookback: int) -> float:
    """Cumulative simple return over the last `lookback` bars (close/close)."""
    if len(bars) < lookback + 1:
        raise ValueError(f"need at least {lookback + 1} bars; got {len(bars)}")
    end = bars[-1].close
    start = bars[-lookback - 1].close
    return (end / start) - 1.0


def _drawdown_from_high(bars: Sequence[Bar], *, lookback: int = 252) -> float:
    """Latest close vs. high over the last `lookback` bars (or all available).

    Negative number when below the high; zero at a new high.
    """
    window = bars[-lookback:] if len(bars) >= lookback else list(bars)
    if not window:
        raise ValueError("empty window")
    high = max(b.close for b in window)
    end = window[-1].close
    return (end / high) - 1.0
