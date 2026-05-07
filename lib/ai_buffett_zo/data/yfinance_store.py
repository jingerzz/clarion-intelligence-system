"""yfinance + CSV cache for daily equity bars.

Default cache root: ~/clarion/data/equities/{TICKER}.csv

Lazy refresh: if the last cached bar is older than `max_age`, the store re-fetches
and merges. Otherwise the cache is returned as-is. yfinance is the only data
source — delayed but free, and intentional per the project's distribution model.

Tests monkeypatch the module-level `_fetch_yfinance` function rather than mocking
the yfinance library directly.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

DEFAULT_CACHE_ROOT = Path.home() / "clarion" / "data" / "equities"


@dataclass(frozen=True, slots=True)
class Bar:
    """One daily OHLCV bar. Volume is shares (not dollar volume)."""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


class EquityStore:
    """Read-through cache for daily equity bars.

    Use:
        store = EquityStore()
        bars = store.history("SPY")            # last 5y, refreshes if stale
        bars = store.history("SPY", start=date(2025, 1, 1))

    Refresh policy:
        max_age=timedelta(days=1)              # default: refresh if last bar > 1 day old
        max_age=timedelta.max                  # offline mode: never refresh
        max_age=timedelta(0)                   # always refresh
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else DEFAULT_CACHE_ROOT
        self.root.mkdir(parents=True, exist_ok=True)

    def cache_path(self, ticker: str) -> Path:
        return self.root / f"{ticker.upper()}.csv"

    def history(
        self,
        ticker: str,
        *,
        start: date | None = None,
        end: date | None = None,
        max_age: timedelta = timedelta(days=1),
        period: str = "5y",
    ) -> list[Bar]:
        """Return cached bars, refreshing lazily if stale or missing.

        period: yfinance period string used on first fetch and on refresh
                ("5y", "1y", "max"). Refresh is full-period — yfinance doesn't
                cleanly support incremental, and the merge handles dedup.
        """
        ticker = ticker.upper()
        cached = self._load(ticker)
        today = date.today()

        if not cached:
            fetched = _fetch_yfinance(ticker, period=period)
            if fetched:
                self._save(ticker, fetched)
            return _slice(fetched, start, end)

        last = cached[-1].date
        if today - last > max_age:
            fetched = _fetch_yfinance(ticker, period=period)
            if fetched:
                cached = _merge(cached, fetched)
                self._save(ticker, cached)

        return _slice(cached, start, end)

    def _load(self, ticker: str) -> list[Bar]:
        path = self.cache_path(ticker)
        if not path.exists():
            return []
        bars: list[Bar] = []
        with path.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                bars.append(
                    Bar(
                        date=date.fromisoformat(row["date"]),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=int(row["volume"]),
                    )
                )
        return bars

    def _save(self, ticker: str, bars: Sequence[Bar]) -> None:
        path = self.cache_path(ticker)
        with path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "open", "high", "low", "close", "volume"])
            for b in bars:
                writer.writerow([b.date.isoformat(), b.open, b.high, b.low, b.close, b.volume])


def _merge(old: Sequence[Bar], new: Sequence[Bar]) -> list[Bar]:
    """De-dup by date; new wins on conflict (yfinance may revise recent bars)."""
    by_date: dict[date, Bar] = {b.date: b for b in old}
    for b in new:
        by_date[b.date] = b
    return sorted(by_date.values(), key=lambda b: b.date)


def _slice(bars: Sequence[Bar], start: date | None, end: date | None) -> list[Bar]:
    return [
        b
        for b in bars
        if (start is None or b.date >= start) and (end is None or b.date <= end)
    ]


def _fetch_yfinance(ticker: str, *, period: str = "5y") -> list[Bar]:
    """Fetch daily bars from yfinance. Returns [] on empty/invalid response.

    Tests monkeypatch this function. Production callers go through EquityStore.
    """
    import yfinance as yf

    df = yf.Ticker(ticker).history(period=period, auto_adjust=False)
    if df is None or df.empty:
        return []

    bars: list[Bar] = []
    for ts, row in df.iterrows():
        d = ts.date() if hasattr(ts, "date") else date.fromisoformat(str(ts)[:10])
        bars.append(
            Bar(
                date=d,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=int(row["Volume"]),
            )
        )
    return bars
