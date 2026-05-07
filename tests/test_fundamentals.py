"""Tests for ai_buffett_zo.evaluation.fundamentals."""

from __future__ import annotations

import math

import pytest

from ai_buffett_zo.evaluation import Fundamentals
from ai_buffett_zo.evaluation.fundamentals import _from_yfinance_info, _num


# ---- _num ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (3.14, 3.14),
        (0, 0.0),
        ("3.14", 3.14),
        ("", None),
        ("   ", None),
        ("not a number", None),
        (None, None),
        ([], None),
        (float("nan"), None),
    ],
)
def test_num_coerces_or_returns_none(value, expected) -> None:
    result = _num(value)
    if expected is None:
        assert result is None
    else:
        assert result == expected


def test_num_zero_passes_through() -> None:
    """0 is meaningful (e.g. dividend yield for non-payers)."""
    assert _num(0) == 0.0
    assert _num(0.0) == 0.0


def test_num_filters_nan_specifically() -> None:
    assert _num(math.nan) is None
    assert _num(float("inf")) == float("inf")  # +inf passes (rare but possible)


# ---- _from_yfinance_info ---------------------------------------------------


def test_from_yfinance_info_full_dict() -> None:
    info = {
        "longName": "NVIDIA Corporation",
        "shortName": "NVDA",
        "marketCap": 3_000_000_000_000.0,
        "trailingPE": 65.5,
        "forwardPE": 35.2,
        "priceToBook": 50.0,
        "profitMargins": 0.55,
        "operatingMargins": 0.62,
        "returnOnEquity": 1.20,
        "returnOnAssets": 0.45,
        "debtToEquity": 25.0,
        "currentRatio": 4.0,
        "freeCashflow": 60_000_000_000.0,
        "operatingCashflow": 65_000_000_000.0,
        "dividendYield": 0.0003,
        "fiftyTwoWeekHigh": 152.0,
        "fiftyTwoWeekLow": 80.0,
        "previousClose": 140.0,
    }
    f = _from_yfinance_info("nvda", info)

    assert isinstance(f, Fundamentals)
    assert f.ticker == "NVDA"  # uppercased
    assert f.company == "NVIDIA Corporation"
    assert f.market_cap == 3e12
    assert f.trailing_pe == 65.5
    assert f.forward_pe == 35.2
    assert f.profit_margin == 0.55
    assert f.return_on_equity == 1.20
    assert f.last_close == 140.0


def test_from_yfinance_info_missing_fields_become_none() -> None:
    f = _from_yfinance_info("XYZ", {})
    assert f.ticker == "XYZ"
    assert f.company is None
    assert f.market_cap is None
    assert f.trailing_pe is None
    assert f.forward_pe is None
    assert f.last_close is None
    assert f.dividend_yield is None


def test_from_yfinance_info_falls_back_to_short_name() -> None:
    f = _from_yfinance_info("BRK.A", {"shortName": "Berkshire"})
    assert f.company == "Berkshire"


def test_from_yfinance_info_last_close_fallback_chain() -> None:
    """previousClose preferred, then regularMarketPreviousClose, then currentPrice."""
    f1 = _from_yfinance_info("X", {"previousClose": 100.0, "currentPrice": 99.0})
    assert f1.last_close == 100.0

    f2 = _from_yfinance_info("X", {"regularMarketPreviousClose": 95.0, "currentPrice": 99.0})
    assert f2.last_close == 95.0

    f3 = _from_yfinance_info("X", {"currentPrice": 99.0})
    assert f3.last_close == 99.0

    f4 = _from_yfinance_info("X", {})
    assert f4.last_close is None


def test_from_yfinance_info_handles_string_numbers() -> None:
    f = _from_yfinance_info("X", {"trailingPE": "20.5", "marketCap": "1000"})
    assert f.trailing_pe == 20.5
    assert f.market_cap == 1000.0


def test_from_yfinance_info_handles_garbage_values() -> None:
    f = _from_yfinance_info("X", {"trailingPE": "N/A", "marketCap": []})
    assert f.trailing_pe is None
    assert f.market_cap is None


def test_from_yfinance_info_zero_dividend_passes_through() -> None:
    """Non-dividend payers report yield = 0; that's the answer, not missing."""
    f = _from_yfinance_info("X", {"dividendYield": 0})
    assert f.dividend_yield == 0.0


def test_from_yfinance_info_handles_none_info_gracefully() -> None:
    """yfinance occasionally returns None for .info — our wrapper passes {} but
    we test the helper directly."""
    f = _from_yfinance_info("X", {})
    assert f.ticker == "X"
    assert all(v is None for v in (f.market_cap, f.trailing_pe, f.last_close))
