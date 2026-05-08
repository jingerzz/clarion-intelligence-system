"""U.S. Treasury daily yield curve fetcher.

Pulls the most recent 3-month T-bill yield from the U.S. Treasury's public
daily-rates CSV. No API key, no rate limits. The 3-month T-bill is the
"true risk-free rate" per docs/ALLOCATION-POLICY.md and the expected-return
framework.

Tests monkeypatch `_fetch_treasury_csv` (the single HTTP seam).
"""

from __future__ import annotations

import csv
import io
import urllib.request
from dataclasses import dataclass
from datetime import date

# Treasury's public CSV endpoint for the daily Treasury yield curve.
# `{year}` is the only template variable. Returns rows with date + tenor cols.
TREASURY_DAILY_RATES_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all"
    "?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv"
)

# Yield-curve column we read. Treasury labels tenors with these strings.
TENOR_3MO = "3 Mo"
TENOR_1YR = "1 Yr"
TENOR_10YR = "10 Yr"


@dataclass(frozen=True)
class TreasuryYield:
    """One observation from the daily yield curve."""

    asof: date
    tenor: str
    rate_pct: float


def fetch_3mo_yield(year: int | None = None) -> TreasuryYield | None:
    """Return the most recent 3-month T-bill yield, or None on any failure."""
    return _fetch_tenor(TENOR_3MO, year=year)


def fetch_1yr_yield(year: int | None = None) -> TreasuryYield | None:
    return _fetch_tenor(TENOR_1YR, year=year)


def fetch_10yr_yield(year: int | None = None) -> TreasuryYield | None:
    return _fetch_tenor(TENOR_10YR, year=year)


def _fetch_tenor(tenor: str, *, year: int | None) -> TreasuryYield | None:
    y = year or date.today().year
    try:
        text = _fetch_treasury_csv(y)
    except Exception:  # noqa: BLE001
        return None
    return _parse_latest(text, tenor=tenor)


def _parse_latest(csv_text: str, *, tenor: str) -> TreasuryYield | None:
    """Find the most-recent row in the CSV that has a non-empty `tenor` value."""
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    if not rows:
        return None
    parsed: list[tuple[date, float]] = []
    for r in rows:
        d = _parse_date(r.get("Date", ""))
        if d is None:
            continue
        v = (r.get(tenor) or "").strip()
        if not v:
            continue
        try:
            parsed.append((d, float(v)))
        except ValueError:
            continue
    if not parsed:
        return None
    parsed.sort(key=lambda t: t[0])
    asof, rate = parsed[-1]
    return TreasuryYield(asof=asof, tenor=tenor, rate_pct=rate)


def _parse_date(s: str) -> date | None:
    """Parse Treasury's MM/DD/YYYY format. Falls back to ISO."""
    s = s.strip()
    if not s:
        return None
    parts = s.split("/")
    if len(parts) == 3:
        try:
            m, d, y = (int(p) for p in parts)
            return date(y, m, d)
        except ValueError:
            return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _fetch_treasury_csv(year: int, timeout: int = 30) -> str:
    """HTTP fetch — production callers go through this; tests monkeypatch it."""
    url = TREASURY_DAILY_RATES_URL.format(year=year)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Clarion Intelligence System (clarion@example.com)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")
