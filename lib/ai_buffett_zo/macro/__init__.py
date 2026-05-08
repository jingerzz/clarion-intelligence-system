"""Macro data + valuation framework: Treasury yields + P/E lookup + allocation decision."""

from ai_buffett_zo.macro.treasury import (
    TENOR_1YR,
    TENOR_3MO,
    TENOR_10YR,
    TREASURY_DAILY_RATES_URL,
    TreasuryYield,
    fetch_1yr_yield,
    fetch_3mo_yield,
    fetch_10yr_yield,
)
from ai_buffett_zo.macro.valuation import (
    AllocationDecision,
    ImpliedReturn,
    Verdict,
    decide_allocation,
    implied_return_from_pe,
)

__all__ = [
    "AllocationDecision",
    "ImpliedReturn",
    "TENOR_10YR",
    "TENOR_1YR",
    "TENOR_3MO",
    "TREASURY_DAILY_RATES_URL",
    "TreasuryYield",
    "Verdict",
    "decide_allocation",
    "fetch_10yr_yield",
    "fetch_1yr_yield",
    "fetch_3mo_yield",
    "implied_return_from_pe",
]
