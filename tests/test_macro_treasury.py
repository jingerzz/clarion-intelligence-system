"""Tests for ai_buffett_zo.macro.treasury."""

from __future__ import annotations

from datetime import date

import pytest

from ai_buffett_zo.macro import TENOR_3MO, TreasuryYield, fetch_3mo_yield
from ai_buffett_zo.macro import treasury


SAMPLE_CSV = """Date,1 Mo,2 Mo,3 Mo,4 Mo,6 Mo,1 Yr,2 Yr,3 Yr,5 Yr,7 Yr,10 Yr,20 Yr,30 Yr
04/30/2026,4.50,4.48,4.45,4.40,4.35,4.20,3.95,3.85,3.80,3.85,3.95,4.30,4.45
05/01/2026,4.51,4.49,4.47,4.41,4.36,4.21,3.96,3.86,3.81,3.86,3.96,4.31,4.46
05/06/2026,4.55,4.52,4.50,4.42,4.38,4.22,3.97,3.87,3.82,3.87,3.97,4.32,4.47
"""

SPARSE_CSV = """Date,1 Mo,2 Mo,3 Mo,4 Mo,6 Mo,1 Yr,2 Yr,3 Yr,5 Yr,7 Yr,10 Yr,20 Yr,30 Yr
04/30/2026,4.50,4.48,4.45,4.40,4.35,4.20,3.95,3.85,3.80,3.85,3.95,4.30,4.45
05/06/2026,,,,,,,,,,,,,
"""


def test_fetch_3mo_yield_returns_latest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(treasury, "_fetch_treasury_csv", lambda y: SAMPLE_CSV)
    y = fetch_3mo_yield(year=2026)
    assert y is not None
    assert y.tenor == TENOR_3MO
    assert y.asof == date(2026, 5, 6)
    assert y.rate_pct == 4.50


def test_fetch_3mo_yield_skips_empty_cells(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the latest row has empty values, fall back to the most recent populated one."""
    monkeypatch.setattr(treasury, "_fetch_treasury_csv", lambda y: SPARSE_CSV)
    y = fetch_3mo_yield(year=2026)
    assert y is not None
    assert y.asof == date(2026, 4, 30)
    assert y.rate_pct == 4.45


def test_fetch_3mo_yield_returns_none_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_y: int) -> str:
        raise OSError("Treasury.gov down")

    monkeypatch.setattr(treasury, "_fetch_treasury_csv", boom)
    assert fetch_3mo_yield(year=2026) is None


def test_fetch_3mo_yield_returns_none_on_empty_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(treasury, "_fetch_treasury_csv", lambda y: "")
    assert fetch_3mo_yield(year=2026) is None


def test_fetch_3mo_yield_returns_none_when_tenor_column_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_no_3mo = "Date,1 Yr\n04/30/2026,4.20\n"
    monkeypatch.setattr(treasury, "_fetch_treasury_csv", lambda y: csv_no_3mo)
    assert fetch_3mo_yield(year=2026) is None


def test_fetch_3mo_yield_returns_none_when_all_values_garbage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_bad = "Date,3 Mo\n04/30/2026,N/A\n05/01/2026,?\n"
    monkeypatch.setattr(treasury, "_fetch_treasury_csv", lambda y: csv_bad)
    assert fetch_3mo_yield(year=2026) is None


def test_parse_date_handles_mmddyyyy_and_iso() -> None:
    assert treasury._parse_date("04/30/2026") == date(2026, 4, 30)
    assert treasury._parse_date("2026-04-30") == date(2026, 4, 30)
    assert treasury._parse_date("") is None
    assert treasury._parse_date("garbage") is None
    assert treasury._parse_date("13/45/2026") is None  # invalid month/day


def test_treasury_yield_dataclass_round_trip() -> None:
    y = TreasuryYield(asof=date(2026, 5, 6), tenor=TENOR_3MO, rate_pct=4.50)
    assert y.asof == date(2026, 5, 6)
    assert y.tenor == "3 Mo"
    assert y.rate_pct == 4.50
