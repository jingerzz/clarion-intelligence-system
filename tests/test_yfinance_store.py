"""Tests for ai_buffett_zo.data.yfinance_store.

The yfinance HTTP path is monkeypatched at the module level — `_fetch_yfinance`
is a single hookable seam.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from ai_buffett_zo.data import Bar, EquityStore
from ai_buffett_zo.data import yfinance_store


def _bar(d: date, close: float = 100.0) -> Bar:
    return Bar(date=d, open=close, high=close, low=close, close=close, volume=1_000_000)


def _series(start: date, n: int, close: float = 100.0) -> list[Bar]:
    return [_bar(start + timedelta(days=i), close + i * 0.1) for i in range(n)]


def test_csv_roundtrip(tmp_path: Path) -> None:
    store = EquityStore(root=tmp_path)
    bars = _series(date(2026, 1, 5), 10)
    store._save("SPY", bars)
    loaded = store._load("SPY")
    assert loaded == bars


def test_history_first_fetch_writes_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetched = _series(date(2026, 1, 5), 5)
    calls: list[str] = []

    def fake_fetch(ticker: str, *, period: str = "5y") -> list[Bar]:
        calls.append(ticker)
        return fetched

    monkeypatch.setattr(yfinance_store, "_fetch_yfinance", fake_fetch)
    store = EquityStore(root=tmp_path)

    bars = store.history("SPY")

    assert calls == ["SPY"]
    assert bars == fetched
    assert store.cache_path("SPY").exists()


def test_history_fresh_cache_skips_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = EquityStore(root=tmp_path)
    today = date.today()
    cached = _series(today - timedelta(days=4), 5)  # last bar is today
    store._save("SPY", cached)

    calls: list[str] = []
    monkeypatch.setattr(
        yfinance_store,
        "_fetch_yfinance",
        lambda ticker, period="5y": calls.append(ticker) or [],
    )

    bars = store.history("SPY")

    assert calls == []
    assert len(bars) == 5


def test_history_stale_cache_triggers_fetch_and_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = EquityStore(root=tmp_path)
    old = _series(date(2026, 1, 1), 5)
    store._save("SPY", old)

    refreshed = old[:-1] + [
        _bar(date(2026, 1, 5), close=999.0),  # revised last bar — new wins
        _bar(date(2026, 1, 6), close=200.0),
    ]
    monkeypatch.setattr(
        yfinance_store,
        "_fetch_yfinance",
        lambda ticker, period="5y": refreshed,
    )

    bars = store.history("SPY", max_age=timedelta(0))  # force stale

    by_date = {b.date: b for b in bars}
    assert by_date[date(2026, 1, 5)].close == 999.0
    assert date(2026, 1, 6) in by_date


def test_history_offline_mode_never_fetches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = EquityStore(root=tmp_path)
    cached = _series(date(2020, 1, 1), 5)  # very stale
    store._save("SPY", cached)

    calls: list[str] = []
    monkeypatch.setattr(
        yfinance_store,
        "_fetch_yfinance",
        lambda ticker, period="5y": calls.append(ticker) or [],
    )

    bars = store.history("SPY", max_age=timedelta.max)

    assert calls == []
    assert bars == cached


def test_history_slice_by_start_and_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = EquityStore(root=tmp_path)
    bars = _series(date(2026, 1, 1), 10)
    store._save("SPY", bars)
    monkeypatch.setattr(
        yfinance_store, "_fetch_yfinance", lambda ticker, period="5y": []
    )

    sliced = store.history(
        "SPY",
        start=date(2026, 1, 4),
        end=date(2026, 1, 7),
        max_age=timedelta.max,
    )
    dates = [b.date for b in sliced]
    assert dates == [
        date(2026, 1, 4),
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
    ]


def test_ticker_uppercased_for_cache_path(tmp_path: Path) -> None:
    store = EquityStore(root=tmp_path)
    assert store.cache_path("spy").name == "SPY.csv"


def test_merge_dedups_and_sorts() -> None:
    a = [_bar(date(2026, 1, 1)), _bar(date(2026, 1, 3))]
    b = [_bar(date(2026, 1, 2)), _bar(date(2026, 1, 3), close=999.0)]
    merged = yfinance_store._merge(a, b)
    assert [x.date for x in merged] == [
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
    ]
    assert merged[-1].close == 999.0  # new wins on conflict
