"""Smoke tests for ai_buffett_zo.voice.templates."""

from __future__ import annotations

from ai_buffett_zo.voice import (
    SIGNATURE,
    cite_filing,
    cite_quote,
    footer,
    header,
    md_table,
    no_data,
    show_math,
)


def test_header_with_subtitle() -> None:
    out = header("Market Regime", "2026-05-06")
    assert out.startswith("## Market Regime")
    assert "2026-05-06" in out


def test_header_without_subtitle() -> None:
    assert header("Test") == "## Test"


def test_footer_includes_signature_and_timestamp() -> None:
    out = footer()
    assert SIGNATURE in out
    assert "UTC" in out


def test_footer_with_sources_and_model() -> None:
    out = footer(
        source_lines=["NVDA 10-K filed 2026-02-21", "SPY as of 2026-05-06"],
        model="zo:openai/gpt-5.4-mini",
    )
    assert "NVDA 10-K" in out
    assert "Sources" in out
    assert "zo:openai/gpt-5.4-mini" in out


def test_md_table() -> None:
    out = md_table(["Ticker", "Price"], [["KO", "$60.12"], ["AAPL", "$215.00"]])
    lines = out.splitlines()
    assert lines[0] == "| Ticker | Price |"
    assert lines[1] == "| --- | --- |"
    assert "KO" in lines[2]
    assert "AAPL" in lines[3]


def test_cite_filing_basic_and_with_page() -> None:
    assert cite_filing("KO", "10-K", "2026-02-21") == "KO 10-K filed 2026-02-21"
    assert cite_filing("KO", "10-K", "2026-02-21", page=14) == "KO 10-K filed 2026-02-21 (p. 14)"


def test_cite_quote() -> None:
    assert cite_quote("SPY", "2026-05-06 16:00 ET") == "SPY as of 2026-05-06 16:00 ET"


def test_no_data_format() -> None:
    out = no_data("yfinance returned no rows for KO")
    assert "Data unavailable" in out
    assert "No estimate substituted" in out


def test_show_math() -> None:
    assert show_math("Hurdle rate", "4.5% + 3.0%", "7.5%") == (
        "- **Hurdle rate**: 4.5% + 3.0% = **7.5%**"
    )
