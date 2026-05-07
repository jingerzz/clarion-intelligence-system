"""Tests for ai_buffett_zo.regime.color."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from ai_buffett_zo.data import Bar
from ai_buffett_zo.regime import HURDLE_PREMIUM_PCT, RegimeSnapshot, snapshot


def _ramp(n: int, *, start_close: float, end_close: float, start_date: date | None = None) -> list[Bar]:
    """n bars where close progresses linearly from start_close to end_close."""
    sd = start_date or date(2025, 1, 1)
    out: list[Bar] = []
    for i in range(n):
        c = start_close + (end_close - start_close) * (i / (n - 1)) if n > 1 else start_close
        out.append(Bar(date=sd + timedelta(days=i), open=c, high=c, low=c, close=c, volume=1))
    return out


def _flat(n: int, close: float = 100.0, start_date: date | None = None) -> list[Bar]:
    return _ramp(n, start_close=close, end_close=close, start_date=start_date)


def _spy_with_drawdown(n: int = 260, peak_at: int = 100, peak_close: float = 200.0) -> list[Bar]:
    """SPY series that hits `peak_close` at index `peak_at`, then falls 25% by the end."""
    sd = date(2025, 1, 1)
    bars: list[Bar] = []
    end_close = peak_close * 0.75  # 25% drawdown
    for i in range(n):
        if i <= peak_at:
            c = 100.0 + (peak_close - 100.0) * (i / peak_at)
        else:
            c = peak_close + (end_close - peak_close) * ((i - peak_at) / (n - 1 - peak_at))
        bars.append(Bar(date=sd + timedelta(days=i), open=c, high=c, low=c, close=c, volume=1))
    return bars


# ---- Color paths -----------------------------------------------------------


def test_green_spy_up_tlt_down() -> None:
    spy = _ramp(70, start_close=100.0, end_close=110.0)        # +10% over 70d
    tlt = _ramp(70, start_close=100.0, end_close=95.0)         # -5% over 70d
    rsp = _ramp(70, start_close=100.0, end_close=110.0)        # tracks SPY
    snap = snapshot(spy, tlt, rsp)
    assert snap.color == "green"
    assert snap.hurdle_rate_pct is None


def test_blue_both_up() -> None:
    spy = _ramp(70, start_close=100.0, end_close=108.0)
    tlt = _ramp(70, start_close=100.0, end_close=104.0)
    rsp = _ramp(70, start_close=100.0, end_close=108.0)
    assert snapshot(spy, tlt, rsp).color == "blue"


def test_orange_flight_to_safety() -> None:
    spy = _ramp(70, start_close=110.0, end_close=104.0)        # SPY -5.5%
    tlt = _ramp(70, start_close=100.0, end_close=104.0)        # TLT +4%
    rsp = _ramp(70, start_close=110.0, end_close=104.0)
    assert snapshot(spy, tlt, rsp).color == "orange"


def test_red_correlation_breakdown() -> None:
    # Need 20d return < -5% to fire the red rule. With a linear 70-bar ramp,
    # the last-20d slice is only ~29% of the total move — so size accordingly.
    spy = _ramp(70, start_close=120.0, end_close=99.0)         # SPY -17.5% total → ~-5.8% last 20d
    tlt = _ramp(70, start_close=100.0, end_close=92.0)         # TLT -8% total → ~-2.5% last 20d
    rsp = _ramp(70, start_close=120.0, end_close=99.0)
    snap = snapshot(spy, tlt, rsp)
    assert snap.color == "red", snap.rationale


def test_orange_narrow_breadth_overrides_blue() -> None:
    # SPY mildly up, TLT mildly up — would be blue, but RSP lags by >5% over 60d
    spy = _ramp(70, start_close=100.0, end_close=110.0)
    tlt = _ramp(70, start_close=100.0, end_close=102.0)
    rsp = _ramp(70, start_close=100.0, end_close=100.0)        # RSP flat → -10% spread vs SPY
    snap = snapshot(spy, tlt, rsp)
    assert snap.color == "orange"
    assert "narrow leadership" in snap.rationale.lower()


def test_danger_drawdown_overrides_everything() -> None:
    spy = _spy_with_drawdown()                                  # -25% from peak
    tlt = _ramp(70, start_close=100.0, end_close=104.0)        # TLT bid (would be orange)
    rsp = _ramp(70, start_close=100.0, end_close=80.0)
    snap = snapshot(spy, tlt, rsp)
    assert snap.color == "danger"
    assert "drawdown" in snap.rationale.lower()


# ---- Hurdle rate -----------------------------------------------------------


@pytest.mark.parametrize(
    ("color_inputs", "expected_color", "rf", "expected_hurdle"),
    [
        # green: rf 4.5 + premium 4.0 = 8.5
        (("up_down",), "green", 4.5, 8.5),
        # blue: rf 4.5 + 4.0 = 8.5
        (("up_up",), "blue", 4.5, 8.5),
        # orange: rf 4.5 + 6.0 = 10.5
        (("flight",), "orange", 4.5, 10.5),
        # red: rf 4.5 + 8.0 = 12.5
        (("redbreak",), "red", 4.5, 12.5),
    ],
)
def test_hurdle_rate(
    color_inputs: tuple[str, ...],
    expected_color: str,
    rf: float,
    expected_hurdle: float,
) -> None:
    label = color_inputs[0]
    if label == "up_down":
        spy = _ramp(70, start_close=100.0, end_close=110.0)
        tlt = _ramp(70, start_close=100.0, end_close=95.0)
        rsp = _ramp(70, start_close=100.0, end_close=110.0)
    elif label == "up_up":
        spy = _ramp(70, start_close=100.0, end_close=108.0)
        tlt = _ramp(70, start_close=100.0, end_close=104.0)
        rsp = _ramp(70, start_close=100.0, end_close=108.0)
    elif label == "flight":
        spy = _ramp(70, start_close=110.0, end_close=104.0)
        tlt = _ramp(70, start_close=100.0, end_close=104.0)
        rsp = _ramp(70, start_close=110.0, end_close=104.0)
    else:  # redbreak
        spy = _ramp(70, start_close=120.0, end_close=99.0)
        tlt = _ramp(70, start_close=100.0, end_close=92.0)
        rsp = _ramp(70, start_close=120.0, end_close=99.0)

    snap = snapshot(spy, tlt, rsp, rf_rate_pct=rf)
    assert snap.color == expected_color
    assert snap.hurdle_rate_pct == pytest.approx(expected_hurdle)


def test_hurdle_premium_table_covers_all_colors() -> None:
    assert set(HURDLE_PREMIUM_PCT.keys()) == {"green", "blue", "orange", "red", "danger"}
    # Premiums should monotonically rise from green to danger
    assert HURDLE_PREMIUM_PCT["green"] <= HURDLE_PREMIUM_PCT["orange"]
    assert HURDLE_PREMIUM_PCT["orange"] <= HURDLE_PREMIUM_PCT["red"]
    assert HURDLE_PREMIUM_PCT["red"] <= HURDLE_PREMIUM_PCT["danger"]


# ---- Edge cases ------------------------------------------------------------


def test_insufficient_history_raises() -> None:
    spy = _flat(50)
    tlt = _flat(50)
    rsp = _flat(50)
    with pytest.raises(ValueError, match="at least 61 bars"):
        snapshot(spy, tlt, rsp)


def test_asof_defaults_to_last_spy_bar() -> None:
    spy = _ramp(70, start_close=100.0, end_close=110.0)
    tlt = _ramp(70, start_close=100.0, end_close=95.0)
    rsp = _ramp(70, start_close=100.0, end_close=110.0)
    snap = snapshot(spy, tlt, rsp)
    assert isinstance(snap, RegimeSnapshot)
    assert snap.asof == spy[-1].date
