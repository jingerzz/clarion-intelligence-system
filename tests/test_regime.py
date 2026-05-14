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
#
# Mapping per regime/color.py:
#   GREEN  SPY up, TLT up        — both assets up, cleanest deploy
#   BLUE   SPY down, TLT up      — bonds hedging properly
#   ORANGE SPY up, TLT down      — equities rallying despite bond stress
#   RED    SPY down ≥5%, TLT down — correlation breakdown
#   DANGER SPY -20% from 252d hi — drawdown override


def test_green_both_up() -> None:
    spy = _ramp(70, start_close=100.0, end_close=108.0)
    tlt = _ramp(70, start_close=100.0, end_close=104.0)
    rsp = _ramp(70, start_close=100.0, end_close=108.0)
    snap = snapshot(spy, tlt, rsp)
    assert snap.color == "green"
    assert snap.hurdle_rate_pct is None


def test_blue_spy_down_tlt_up() -> None:
    spy = _ramp(70, start_close=110.0, end_close=104.0)        # SPY -5.5%
    tlt = _ramp(70, start_close=100.0, end_close=104.0)        # TLT +4%
    rsp = _ramp(70, start_close=110.0, end_close=104.0)
    assert snapshot(spy, tlt, rsp).color == "blue"


def test_orange_spy_up_tlt_down() -> None:
    spy = _ramp(70, start_close=100.0, end_close=110.0)        # +10%
    tlt = _ramp(70, start_close=100.0, end_close=95.0)         # -5%
    rsp = _ramp(70, start_close=100.0, end_close=110.0)
    assert snapshot(spy, tlt, rsp).color == "orange"


def test_red_correlation_breakdown() -> None:
    # Need 20d return < -5% to fire the red rule. With a linear 70-bar ramp,
    # the last-20d slice is only ~29% of the total move — so size accordingly.
    spy = _ramp(70, start_close=120.0, end_close=99.0)         # SPY -17.5% total → ~-5.8% last 20d
    tlt = _ramp(70, start_close=100.0, end_close=92.0)         # TLT -8% total → ~-2.5% last 20d
    rsp = _ramp(70, start_close=120.0, end_close=99.0)
    snap = snapshot(spy, tlt, rsp)
    assert snap.color == "red", snap.rationale


def test_danger_drawdown_overrides_everything() -> None:
    spy = _spy_with_drawdown()                                  # -25% from peak
    tlt = _ramp(70, start_close=100.0, end_close=104.0)        # TLT bid (would be blue otherwise)
    rsp = _ramp(70, start_close=100.0, end_close=80.0)
    snap = snapshot(spy, tlt, rsp)
    assert snap.color == "danger"
    assert "drawdown" in snap.rationale.lower()


# ---- Daily fire flags ------------------------------------------------------


def _series_with_last_day(
    spy_prev_close: float,
    spy_last_close: float,
    tlt_prev_close: float,
    tlt_last_close: float,
    *,
    spy_vol_today: int = 1_000_000,
    spy_vol_prior_avg: int = 1_000_000,
    n: int = 70,
) -> tuple[list[Bar], list[Bar], list[Bar]]:
    """Build SPY/TLT/RSP series of length n where the LAST bar has a
    specific 1-day move and SPY volume profile (today vs trailing avg)
    that the daily-flag rules can fire on. The 20d series is held flat
    so the color is dominated by the last day's tiny effects only.

    SPY's last bar's close = spy_last_close; bar n-2's close = spy_prev_close.
    SPY's last bar's volume = spy_vol_today; earlier bars use spy_vol_prior_avg.
    """
    sd = date(2025, 1, 1)
    # SPY: hold flat at spy_prev_close for first n-1 bars, last bar = spy_last_close
    spy: list[Bar] = []
    for i in range(n - 1):
        spy.append(
            Bar(
                date=sd + timedelta(days=i),
                open=spy_prev_close,
                high=spy_prev_close,
                low=spy_prev_close,
                close=spy_prev_close,
                volume=spy_vol_prior_avg,
            )
        )
    spy.append(
        Bar(
            date=sd + timedelta(days=n - 1),
            open=spy_last_close,
            high=spy_last_close,
            low=spy_last_close,
            close=spy_last_close,
            volume=spy_vol_today,
        )
    )
    # TLT: same pattern with its own last-bar close
    tlt: list[Bar] = []
    for i in range(n - 1):
        tlt.append(
            Bar(
                date=sd + timedelta(days=i),
                open=tlt_prev_close,
                high=tlt_prev_close,
                low=tlt_prev_close,
                close=tlt_prev_close,
                volume=1,
            )
        )
    tlt.append(
        Bar(
            date=sd + timedelta(days=n - 1),
            open=tlt_last_close,
            high=tlt_last_close,
            low=tlt_last_close,
            close=tlt_last_close,
            volume=1,
        )
    )
    # RSP: track SPY exactly so breadth doesn't fire
    rsp = [
        Bar(
            date=b.date, open=b.open, high=b.high, low=b.low, close=b.close, volume=1,
        )
        for b in spy
    ]
    return spy, tlt, rsp


def test_big_blue_day_fires_on_strong_negative_correlation() -> None:
    # SPY 1d: -1.5%, TLT 1d: +1.5% → fire
    spy, tlt, rsp = _series_with_last_day(100.0, 98.5, 100.0, 101.5)
    snap = snapshot(spy, tlt, rsp)
    assert snap.big_blue_day is True
    assert snap.capitulation is False
    assert snap.spy_ret_1d == pytest.approx(-0.015)
    assert snap.tlt_ret_1d == pytest.approx(0.015)


def test_big_blue_day_does_not_fire_when_spy_drop_too_small() -> None:
    # SPY 1d: -0.5%, TLT 1d: +1.5% → no fire (SPY threshold not met)
    spy, tlt, rsp = _series_with_last_day(100.0, 99.5, 100.0, 101.5)
    assert snapshot(spy, tlt, rsp).big_blue_day is False


def test_big_blue_day_does_not_fire_when_tlt_not_up_enough() -> None:
    # SPY 1d: -1.5%, TLT 1d: +0.5% → no fire (TLT threshold not met)
    spy, tlt, rsp = _series_with_last_day(100.0, 98.5, 100.0, 100.5)
    assert snapshot(spy, tlt, rsp).big_blue_day is False


def test_capitulation_fires_on_high_volume_both_down() -> None:
    # SPY 1d: -1.5%, TLT 1d: -0.5%, volume 3M vs prior 1M avg (3x > 1.5x threshold)
    spy, tlt, rsp = _series_with_last_day(
        100.0, 98.5, 100.0, 99.5,
        spy_vol_today=3_000_000, spy_vol_prior_avg=1_000_000,
    )
    snap = snapshot(spy, tlt, rsp)
    assert snap.capitulation is True
    assert snap.big_blue_day is False  # TLT is down, not up


def test_capitulation_does_not_fire_on_normal_volume() -> None:
    # Same SPY/TLT moves but normal volume (1x)
    spy, tlt, rsp = _series_with_last_day(
        100.0, 98.5, 100.0, 99.5,
        spy_vol_today=1_000_000, spy_vol_prior_avg=1_000_000,
    )
    assert snapshot(spy, tlt, rsp).capitulation is False


def test_capitulation_does_not_fire_when_tlt_up() -> None:
    # SPY down, TLT UP, volume high — flight to safety, not capitulation. big_blue_day fires instead.
    spy, tlt, rsp = _series_with_last_day(
        100.0, 98.5, 100.0, 101.5,
        spy_vol_today=3_000_000, spy_vol_prior_avg=1_000_000,
    )
    snap = snapshot(spy, tlt, rsp)
    assert snap.capitulation is False
    assert snap.big_blue_day is True


# ---- Breadth flag (separate from color) ------------------------------------


def test_breadth_flag_narrow_when_rsp_lags() -> None:
    # GREEN quadrant (SPY up, TLT up) but RSP flat → RSP lags by ~10% over 60d
    spy = _ramp(70, start_close=100.0, end_close=110.0)
    tlt = _ramp(70, start_close=100.0, end_close=102.0)
    rsp = _ramp(70, start_close=100.0, end_close=100.0)
    snap = snapshot(spy, tlt, rsp)
    assert snap.color == "green", "narrow breadth must NOT override the color"
    assert snap.breadth_flag == "narrow"


def test_breadth_flag_broad_when_rsp_keeps_up() -> None:
    spy = _ramp(70, start_close=100.0, end_close=108.0)
    tlt = _ramp(70, start_close=100.0, end_close=104.0)
    rsp = _ramp(70, start_close=100.0, end_close=108.0)        # tracks SPY
    snap = snapshot(spy, tlt, rsp)
    assert snap.breadth_flag == "broad"


# ---- Hurdle rate -----------------------------------------------------------


@pytest.mark.parametrize(
    ("scenario", "expected_color", "rf", "expected_hurdle"),
    [
        # green (both up): rf 4.5 + premium 4.0 = 8.5
        ("up_up", "green", 4.5, 8.5),
        # blue (SPY down, TLT up): rf 4.5 + 4.0 = 8.5
        ("down_up", "blue", 4.5, 8.5),
        # orange (SPY up, TLT down): rf 4.5 + 6.0 = 10.5
        ("up_down", "orange", 4.5, 10.5),
        # red (SPY down ≥5%, TLT down): rf 4.5 + 8.0 = 12.5
        ("redbreak", "red", 4.5, 12.5),
    ],
)
def test_hurdle_rate(
    scenario: str,
    expected_color: str,
    rf: float,
    expected_hurdle: float,
) -> None:
    if scenario == "up_up":
        spy = _ramp(70, start_close=100.0, end_close=108.0)
        tlt = _ramp(70, start_close=100.0, end_close=104.0)
        rsp = _ramp(70, start_close=100.0, end_close=108.0)
    elif scenario == "down_up":
        spy = _ramp(70, start_close=110.0, end_close=104.0)
        tlt = _ramp(70, start_close=100.0, end_close=104.0)
        rsp = _ramp(70, start_close=110.0, end_close=104.0)
    elif scenario == "up_down":
        spy = _ramp(70, start_close=100.0, end_close=110.0)
        tlt = _ramp(70, start_close=100.0, end_close=95.0)
        rsp = _ramp(70, start_close=100.0, end_close=110.0)
    else:  # redbreak
        spy = _ramp(70, start_close=120.0, end_close=99.0)
        tlt = _ramp(70, start_close=100.0, end_close=92.0)
        rsp = _ramp(70, start_close=120.0, end_close=99.0)

    snap = snapshot(spy, tlt, rsp, rf_rate_pct=rf)
    assert snap.color == expected_color
    assert snap.hurdle_rate_pct == pytest.approx(expected_hurdle)


def test_hurdle_premium_table_covers_all_colors() -> None:
    assert set(HURDLE_PREMIUM_PCT.keys()) == {"green", "blue", "orange", "red", "danger"}
    # Premiums should monotonically rise from green/blue (deploy regimes) to danger
    assert HURDLE_PREMIUM_PCT["green"] <= HURDLE_PREMIUM_PCT["orange"]
    assert HURDLE_PREMIUM_PCT["blue"] <= HURDLE_PREMIUM_PCT["orange"]
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
    spy = _ramp(70, start_close=100.0, end_close=108.0)
    tlt = _ramp(70, start_close=100.0, end_close=104.0)
    rsp = _ramp(70, start_close=100.0, end_close=108.0)
    snap = snapshot(spy, tlt, rsp)
    assert isinstance(snap, RegimeSnapshot)
    assert snap.asof == spy[-1].date
