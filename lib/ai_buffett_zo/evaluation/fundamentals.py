"""Quality / quantitative snapshot from yfinance .info.

yfinance's `Ticker.info` returns a wide dict with mixed-quality fields. We
extract a small, well-typed subset and surface missing fields explicitly via
`Optional`. The data is point-in-time and can drift from the latest filing —
callers should warn the user.

`fetch_fundamentals` is the single hookable seam — tests monkeypatch it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Fundamentals:
    """Subset of yfinance .info we surface for Buffett-lens evaluation.

    Any field can be None when yfinance didn't return it (common for small
    caps, OTC tickers, foreign listings).

    Margin / yield / return fields are decimals (0.25 = 25%), not percent.
    """

    ticker: str
    company: str | None
    market_cap: float | None
    trailing_pe: float | None
    forward_pe: float | None
    price_to_book: float | None
    profit_margin: float | None
    operating_margin: float | None
    return_on_equity: float | None
    return_on_assets: float | None
    debt_to_equity: float | None
    current_ratio: float | None
    free_cash_flow: float | None        # USD trailing 12mo
    operating_cash_flow: float | None   # USD trailing 12mo
    dividend_yield: float | None
    week52_high: float | None
    week52_low: float | None
    last_close: float | None


def fetch_fundamentals(ticker: str) -> Fundamentals:
    """Fetch yfinance .info and normalize into Fundamentals.

    Tests monkeypatch this. Production callers always go through here.
    """
    import yfinance as yf

    info = yf.Ticker(ticker).info or {}
    return _from_yfinance_info(ticker, info)


def _from_yfinance_info(ticker: str, info: dict[str, Any]) -> Fundamentals:
    """Map yfinance's loose dict into a typed Fundamentals."""
    return Fundamentals(
        ticker=ticker.upper(),
        company=info.get("longName") or info.get("shortName"),
        market_cap=_num(info.get("marketCap")),
        trailing_pe=_num(info.get("trailingPE")),
        forward_pe=_num(info.get("forwardPE")),
        price_to_book=_num(info.get("priceToBook")),
        profit_margin=_num(info.get("profitMargins")),
        operating_margin=_num(info.get("operatingMargins")),
        return_on_equity=_num(info.get("returnOnEquity")),
        return_on_assets=_num(info.get("returnOnAssets")),
        debt_to_equity=_num(info.get("debtToEquity")),
        current_ratio=_num(info.get("currentRatio")),
        free_cash_flow=_num(info.get("freeCashflow")),
        operating_cash_flow=_num(info.get("operatingCashflow")),
        dividend_yield=_dividend_yield_norm(info.get("dividendYield")),
        week52_high=_num(info.get("fiftyTwoWeekHigh")),
        week52_low=_num(info.get("fiftyTwoWeekLow")),
        last_close=_num(
            info.get("previousClose")
            or info.get("regularMarketPreviousClose")
            or info.get("currentPrice")
        ),
    )


def _dividend_yield_norm(value: Any) -> float | None:
    """Normalize yfinance's dividendYield to decimal form (0.0259 = 2.59%).

    yfinance returns dividendYield as a percentage value (e.g. 2.59 for
    2.59%) — uniquely among the yield/margin fields in `Ticker.info`,
    which return decimals (profitMargins=0.55 for 55%, returnOnEquity=1.20
    for 120%, etc). Without normalization here, eval.py's `_fmt_pct`
    multiplies by 100 a second time and renders KO as "259.00%".

    Heuristic: values > 1.0 are treated as percentages and divided by 100;
    values <= 1.0 pass through as already-decimal. The threshold is
    unambiguous because real-world dividend yields cap around 10-15% —
    a yfinance value of 12.0 unambiguously means 12%, while a value of
    0.12 unambiguously means 12% in the legacy decimal contract. This
    keeps the helper correct across yfinance version drift.
    """
    n = _num(value)
    if n is None:
        return None
    return n / 100.0 if n > 1.0 else n


def _num(value: Any) -> float | None:
    """Coerce to float, return None for missing/empty/non-numeric values.

    yfinance returns NaN-equivalents and empty strings for missing fields.
    We intentionally pass through 0.0 — for fields where 0 is meaningful
    (dividend yield = 0 for non-dividend payers), the zero is the answer.
    """
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    # NaN check — float('nan') != float('nan')
    return f if f == f else None
