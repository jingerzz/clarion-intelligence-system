"""Tests for ai_buffett_zo.secrag.recovery — Phase 2 pointer recovery.

HTTP is monkeypatched at loader.py's `_get_text` seam. Storage cache uses
tmp_path fixtures so tests don't touch real ~/clarion data.
"""

from __future__ import annotations

import urllib.error
from datetime import date
from pathlib import Path

import pytest

from ai_buffett_zo.secrag import loader
from ai_buffett_zo.secrag.loader import FilingMetadata
from ai_buffett_zo.secrag.recovery import (
    RECOVERED_VIA_FILING_SUMMARY,
    _strip_xbrl_metadata,
    is_recoverable,
    recover_pointer_sections,
)
from ai_buffett_zo.secrag.sections import Section
from ai_buffett_zo.secrag.storage import (
    load_filing_summary,
    load_r_file,
)


# ---- Fixtures ---------------------------------------------------------------


def _metadata(ticker: str = "IBM", accession: str = "0000051143-26-000010") -> FilingMetadata:
    return FilingMetadata(
        cik="0000051143",
        ticker=ticker,
        company="International Business Machines Corp",
        form="10-K",
        filed=date(2026, 2, 24),
        period=date(2025, 12, 31),
        accession=accession,
        primary_doc="ibm-20251231.htm",
        primary_doc_url="https://www.sec.gov/Archives/edgar/data/51143/000005114326000010/ibm-20251231.htm",
    )


# Minimal but realistic FilingSummary.xml structure. Matches the shape on real
# IBM/KO/PG/NVDA filings — multiple <Report> entries, MenuCategory varies.
_IBM_FILING_SUMMARY_XML = """<?xml version="1.0" encoding="utf-8"?>
<FilingSummary>
  <Version>2.x</Version>
  <ProcessingTime/>
  <ReportFormat>Xml</ReportFormat>
  <MyReports>
    <Report instance="ibm-20251231.htm">
      <IsDefault>true</IsDefault>
      <HasEmbeddedReports>false</HasEmbeddedReports>
      <HtmlFileName>R1.htm</HtmlFileName>
      <LongName>0000001 - Document - Cover Page</LongName>
      <ReportType>Sheet</ReportType>
      <Role>http://example.com/role/CoverPage</Role>
      <ShortName>Cover Page</ShortName>
      <MenuCategory>Cover</MenuCategory>
      <Position>1</Position>
    </Report>
    <Report instance="ibm-20251231.htm">
      <IsDefault>false</IsDefault>
      <HtmlFileName>R3.htm</HtmlFileName>
      <LongName>1003003 - Statement - CONSOLIDATED INCOME STATEMENT</LongName>
      <ShortName>CONSOLIDATED INCOME STATEMENT</ShortName>
      <MenuCategory>Statements</MenuCategory>
      <Position>3</Position>
    </Report>
    <Report instance="ibm-20251231.htm">
      <IsDefault>false</IsDefault>
      <HtmlFileName>R4.htm</HtmlFileName>
      <LongName>1003004 - Statement - CONSOLIDATED BALANCE SHEET</LongName>
      <ShortName>CONSOLIDATED BALANCE SHEET</ShortName>
      <MenuCategory>Statements</MenuCategory>
      <Position>4</Position>
    </Report>
    <Report instance="ibm-20251231.htm">
      <IsDefault>false</IsDefault>
      <HtmlFileName>R5.htm</HtmlFileName>
      <LongName>1003005 - Statement - CONSOLIDATED STATEMENT OF CASH FLOWS</LongName>
      <ShortName>CONSOLIDATED STATEMENT OF CASH FLOWS</ShortName>
      <MenuCategory>Statements</MenuCategory>
      <Position>5</Position>
    </Report>
    <Report instance="ibm-20251231.htm">
      <IsDefault>false</IsDefault>
      <HtmlFileName>R20.htm</HtmlFileName>
      <LongName>2001020 - Disclosure - Significant Accounting Policies</LongName>
      <ShortName>Significant Accounting Policies (Notes)</ShortName>
      <MenuCategory>Notes</MenuCategory>
      <Position>20</Position>
    </Report>
  </MyReports>
  <InputFiles/>
  <SupplementalFiles/>
  <BaseTaxonomies/>
  <HasPresentationLinkbase>true</HasPresentationLinkbase>
  <HasCalculationLinkbase>true</HasCalculationLinkbase>
</FilingSummary>
"""

# Canned R-file HTML — each statement is one mock SEC-rendered table.
_R_FILE_CONTENT = {
    "R1.htm": "<html><body><h1>Cover Page</h1><p>IBM 2025 10-K cover</p></body></html>",
    "R3.htm": (
        "<html><body><h1>Consolidated Income Statement</h1>"
        "<table><tr><td>Total revenue</td><td>$62,753</td></tr>"
        "<tr><td>Net income</td><td>$7,500</td></tr></table></body></html>"
    ),
    "R4.htm": (
        "<html><body><h1>Consolidated Balance Sheet</h1>"
        "<table><tr><td>Total assets</td><td>$130,000</td></tr>"
        "<tr><td>Total liabilities</td><td>$110,000</td></tr></table></body></html>"
    ),
    "R5.htm": (
        "<html><body><h1>Consolidated Statement of Cash Flows</h1>"
        "<table><tr><td>Operating cash flow</td><td>$13,500</td></tr></table></body></html>"
    ),
    "R20.htm": "<html><body><h1>Significant Accounting Policies</h1><p>...</p></body></html>",
}


def _patch_recovery_http(
    monkeypatch: pytest.MonkeyPatch,
    *,
    summary_xml: str | None = _IBM_FILING_SUMMARY_XML,
    r_files: dict[str, str] | None = None,
    summary_status: int = 200,
    r_file_status: dict[str, int] | None = None,
) -> dict[str, list[str]]:
    """Install a fake `_get_text` keyed by URL.

    Returns a dict capturing every URL fetched, so tests can assert
    cache-hit vs cache-miss behavior.
    """
    if r_files is None:
        r_files = _R_FILE_CONTENT
    if r_file_status is None:
        r_file_status = {}
    captured: dict[str, list[str]] = {"urls": []}

    def fake_get_text(url: str, *, user_agent: str, timeout: int = 60) -> str:
        captured["urls"].append(url)
        if "FilingSummary.xml" in url:
            if summary_status == 404:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
            if summary_xml is None:
                raise AssertionError("test asked for FilingSummary but xml is None")
            return summary_xml
        # R-file path: figure out which one from the URL
        for name, content in r_files.items():
            if url.endswith(name):
                if r_file_status.get(name, 200) == 404:
                    raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
                if r_file_status.get(name, 200) >= 500:
                    raise urllib.error.HTTPError(url, 500, "Server Error", {}, None)  # type: ignore[arg-type]
                return content
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(loader, "_get_text", fake_get_text)
    return captured


def _pointer_section(label: str = "financial_statements", target: str = "annual_report_same_doc") -> Section:
    """A Section the way Phase 0 produces it for IBM-style pointer body."""
    return Section(
        label=label,
        title="Item 8. Financial Statements",
        text="The information required by this Item is included in the Annual Report to Stockholders filed as Exhibit 13.",
        char_start=10000,
        char_end=10120,
        is_pointer_only=True,
        pointer_target=target,
    )


def _substantive_section() -> Section:
    """A non-pointer section that should never be touched by Phase 2."""
    return Section(
        label="business",
        title="Item 1. Business",
        text="IBM is a global technology company. " * 100,
        char_start=0,
        char_end=4000,
    )


# ---- is_recoverable --------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "is_pointer", "target", "expected"),
    [
        ("financial_statements", True, "annual_report_same_doc", True),
        ("mdna", True, "annual_report_same_doc", True),
        ("financial_statements", True, "unknown", True),
        ("mdna", True, "unknown", True),
        # def14a target is Phase 1's job, not Phase 2's
        ("financial_statements", True, "def14a", False),
        # parser_bug is recoverable — see RECOVERABLE_TARGETS comment in
        # recovery.py for why (KO classified as parser_bug after Phase 0 trimmed
        # its "Refer to" prefix; FilingSummary recovery handles it gracefully)
        ("financial_statements", True, "parser_bug", True),
        ("mdna", True, "parser_bug", True),
        # substantive section
        ("financial_statements", False, None, False),
        # other labels don't qualify even if pointer
        ("business", True, "annual_report_same_doc", False),
        ("risk_factors", True, "annual_report_same_doc", False),
    ],
)
def test_is_recoverable(label, is_pointer, target, expected) -> None:
    s = Section(
        label=label,
        title="T",
        text="",
        char_start=0,
        char_end=10,
        is_pointer_only=is_pointer,
        pointer_target=target,
    )
    assert is_recoverable(s) is expected


# ---- recover_pointer_sections — happy path ---------------------------------


def test_recover_replaces_pointer_with_r_file_content(monkeypatch, tmp_path: Path) -> None:
    """Happy path: pointer Item 8 → text becomes concatenated R-file content."""
    _patch_recovery_http(monkeypatch)
    sections = [_substantive_section(), _pointer_section()]

    out = recover_pointer_sections(_metadata(), sections, tmp_path)

    # Substantive section unchanged
    assert out[0].text == sections[0].text
    assert out[0].recovered_via is None
    assert out[0].is_pointer_only is False

    # Pointer section recovered
    recovered = out[1]
    assert recovered.recovered_via == RECOVERED_VIA_FILING_SUMMARY
    assert recovered.is_pointer_only is True  # provenance preserved
    assert "Consolidated Income Statement" in recovered.text
    assert "Total revenue" in recovered.text
    assert "Consolidated Balance Sheet" in recovered.text
    assert "Total assets" in recovered.text
    assert "Consolidated Statement of Cash Flows" in recovered.text
    # Notes (Significant Accounting Policies) should NOT be in the default
    # recovered text — only Statements
    assert "Significant Accounting Policies" not in recovered.text
    # Cover page should also be excluded
    assert "IBM 2025 10-K cover" not in recovered.text


def test_recover_handles_target_unknown(monkeypatch, tmp_path: Path) -> None:
    """`unknown` target (the KO/NVDA/INTC majority case) also triggers recovery."""
    _patch_recovery_http(monkeypatch)
    sections = [_pointer_section(target="unknown")]
    out = recover_pointer_sections(_metadata(), sections, tmp_path)
    assert out[0].recovered_via == RECOVERED_VIA_FILING_SUMMARY


def test_recover_skips_def14a_target(monkeypatch, tmp_path: Path) -> None:
    """def14a is Phase 1's territory; Phase 2 leaves it alone."""
    captured = _patch_recovery_http(monkeypatch)
    sections = [_pointer_section(target="def14a")]
    out = recover_pointer_sections(_metadata(), sections, tmp_path)
    assert out[0].recovered_via is None
    assert out[0].text == sections[0].text
    # No HTTP should have happened — early-exit because no recoverable section
    assert captured["urls"] == []


def test_recover_attempts_recovery_on_parser_bug_target(
    monkeypatch, tmp_path: Path
) -> None:
    """parser_bug sections get recovery attempt — KO-style cases (Phase 0
    trimmed the pointer prefix) succeed when FilingSummary exists.

    Per canonical Zo's PR #29 real-data review: KO's Item 8 was getting
    classified as parser_bug because the curated regex stripped its
    "Refer to" prefix, leaving a body with no pointer-language tokens.
    KO has a valid FilingSummary; attempting recovery is the right move.
    """
    _patch_recovery_http(monkeypatch)
    sections = [_pointer_section(target="parser_bug")]
    out = recover_pointer_sections(_metadata(), sections, tmp_path)
    assert out[0].recovered_via == RECOVERED_VIA_FILING_SUMMARY
    assert "Consolidated Income Statement" in out[0].text


def test_recover_parser_bug_gracefully_skips_when_no_filing_summary(
    monkeypatch, tmp_path: Path
) -> None:
    """True parser bugs (PWR business='and', MSFT TOC fragments) typically
    don't have FilingSummary entries that match — recovery attempts but
    finds nothing, leaves the section unchanged with recovered_via=None."""
    _patch_recovery_http(monkeypatch, summary_status=404)
    sections = [_pointer_section(target="parser_bug")]
    out = recover_pointer_sections(_metadata(), sections, tmp_path)
    assert out[0].recovered_via is None
    assert out[0].is_pointer_only is True  # provenance preserved
    assert out[0].text == sections[0].text  # unchanged


def test_recover_no_op_when_no_recoverable_sections(monkeypatch, tmp_path: Path) -> None:
    """No recoverable sections → no HTTP, return list unchanged."""
    captured = _patch_recovery_http(monkeypatch)
    sections = [_substantive_section()]
    out = recover_pointer_sections(_metadata(), sections, tmp_path)
    assert out == sections
    assert captured["urls"] == []


# ---- Caching ---------------------------------------------------------------


def test_recover_caches_filing_summary_and_r_files(monkeypatch, tmp_path: Path) -> None:
    """Cache cold → fetch + persist. Cache warm → no further HTTP."""
    captured = _patch_recovery_http(monkeypatch)
    sections = [_pointer_section()]
    md = _metadata()

    # First run: cold cache
    recover_pointer_sections(md, sections, tmp_path)
    first_run_urls = list(captured["urls"])
    assert any("FilingSummary.xml" in u for u in first_run_urls)
    assert any(u.endswith("R3.htm") for u in first_run_urls)
    # Cache files written
    assert load_filing_summary(tmp_path, md.ticker, md.accession) is not None
    assert load_r_file(tmp_path, md.ticker, md.accession, "R3.htm") is not None
    assert load_r_file(tmp_path, md.ticker, md.accession, "R4.htm") is not None

    # Second run: cache warm
    captured["urls"].clear()
    recover_pointer_sections(md, sections, tmp_path)
    assert captured["urls"] == []  # zero HTTP on warm cache


# ---- Graceful degradation -------------------------------------------------


def test_recover_returns_unchanged_when_no_filing_summary(
    monkeypatch, tmp_path: Path
) -> None:
    """Pre-iXBRL filing (404 on FilingSummary) — section stays as pointer."""
    _patch_recovery_http(monkeypatch, summary_status=404)
    sections = [_pointer_section()]
    out = recover_pointer_sections(_metadata(), sections, tmp_path)
    assert out[0].recovered_via is None
    assert out[0].is_pointer_only is True
    assert out[0].text == sections[0].text


def test_recover_continues_when_one_r_file_fails(
    monkeypatch, tmp_path: Path
) -> None:
    """One R-file 500s → recovery still succeeds with the others."""
    _patch_recovery_http(
        monkeypatch,
        r_file_status={"R4.htm": 500},  # Balance Sheet HTTP-500s
    )
    sections = [_pointer_section()]
    out = recover_pointer_sections(_metadata(), sections, tmp_path)
    # Still recovered with the surviving statements
    assert out[0].recovered_via == RECOVERED_VIA_FILING_SUMMARY
    assert "Total revenue" in out[0].text         # R3 succeeded
    assert "Total assets" not in out[0].text      # R4 failed
    assert "Operating cash flow" in out[0].text   # R5 succeeded


def test_recover_returns_unchanged_when_no_statements_in_manifest(
    monkeypatch, tmp_path: Path
) -> None:
    """Manifest exists but has no `MenuCategory="Statements"` reports."""
    cover_only_xml = """<?xml version="1.0" encoding="utf-8"?>
<FilingSummary>
  <MyReports>
    <Report instance="x.htm">
      <HtmlFileName>R1.htm</HtmlFileName>
      <ShortName>Cover Page</ShortName>
      <LongName>Cover Page</LongName>
      <MenuCategory>Cover</MenuCategory>
      <Position>1</Position>
    </Report>
  </MyReports>
</FilingSummary>
"""
    _patch_recovery_http(monkeypatch, summary_xml=cover_only_xml)
    sections = [_pointer_section()]
    out = recover_pointer_sections(_metadata(), sections, tmp_path)
    assert out[0].recovered_via is None


# ---- FilingSummary parser unit tests --------------------------------------


def test_parse_filing_summary_extracts_all_reports() -> None:
    summary = loader._parse_filing_summary(_IBM_FILING_SUMMARY_XML)
    assert len(summary.reports) == 5
    short_names = [r.short_name for r in summary.reports]
    assert "CONSOLIDATED INCOME STATEMENT" in short_names
    assert "CONSOLIDATED BALANCE SHEET" in short_names


def test_filing_summary_statements_filters_to_menu_category() -> None:
    summary = loader._parse_filing_summary(_IBM_FILING_SUMMARY_XML)
    statements = summary.statements()
    assert len(statements) == 3
    assert all(r.menu_category == "Statements" for r in statements)


def test_parse_filing_summary_tolerates_missing_optional_fields() -> None:
    """A <Report> without MenuCategory shouldn't crash the parser."""
    xml = """<?xml version="1.0"?>
<FilingSummary><MyReports>
  <Report><ShortName>X</ShortName><HtmlFileName>R1.htm</HtmlFileName></Report>
</MyReports></FilingSummary>
"""
    summary = loader._parse_filing_summary(xml)
    assert summary.reports[0].menu_category == ""
    assert summary.reports[0].position == 0


# ---- iXBRL noise stripping (issue #43) ------------------------------------


def test_strip_xbrl_metadata_removes_type_and_period_lines() -> None:
    """Element balance/period-type descriptor lines are dropped."""
    text = (
        "Total revenue\n"
        "62,753\n"
        "Type: credit\n"
        "Period Type: duration\n"
        "Net income\n"
        "7,500\n"
    )
    out = _strip_xbrl_metadata(text)
    assert "Type: credit" not in out
    assert "Period Type: duration" not in out
    # Real data survives
    assert "Total revenue" in out
    assert "62,753" in out
    assert "Net income" in out
    assert "7,500" in out


def test_strip_xbrl_metadata_removes_definition_markers() -> None:
    text = (
        "Cash flows from operations\n"
        "13,500\n"
        "X — Definition\n"
        "No definition available.\n"
        "Definition\n"
        "Proceeds from new debt\n"
        "8,391\n"
    )
    out = _strip_xbrl_metadata(text)
    assert "X — Definition" not in out
    assert "No definition available" not in out
    # The bare "Definition" label line is gone, but data rows remain
    assert "\nDefinition\n" not in f"\n{out}\n"
    assert "Cash flows from operations" in out
    assert "13,500" in out
    assert "Proceeds from new debt" in out
    assert "8,391" in out


def test_strip_xbrl_metadata_removes_taxonomy_uris() -> None:
    text = (
        "Total assets\n"
        "130,000\n"
        "http://fasb.org/us-gaap/2025#Assets\n"
        "http://www.xbrl.org/2003/role/label\n"
        "Total liabilities\n"
        "110,000\n"
    )
    out = _strip_xbrl_metadata(text)
    assert "fasb.org" not in out
    assert "xbrl.org" not in out
    assert "Total assets" in out
    assert "130,000" in out
    assert "Total liabilities" in out


def test_strip_xbrl_metadata_preserves_clean_text() -> None:
    """Text with no iXBRL noise passes through unchanged (modulo trailing ws)."""
    text = (
        "CONSOLIDATED INCOME STATEMENT\n"
        "Total revenue 62,753 60,530 57,351\n"
        "Cost of goods sold (31,000)\n"
        "Net income 7,500"
    )
    out = _strip_xbrl_metadata(text)
    assert out == text.strip()


def test_strip_xbrl_metadata_does_not_eat_data_mentioning_credit() -> None:
    """A real line that happens to contain 'credit' mid-sentence is kept.

    The filter anchors on line-start 'Type: credit', not the word 'credit'
    anywhere — so revenue/credit-loss line items survive.
    """
    text = (
        "Provision for credit losses\n"
        "1,234\n"
        "Credit card receivables, net\n"
        "45,678\n"
    )
    out = _strip_xbrl_metadata(text)
    assert "Provision for credit losses" in out
    assert "Credit card receivables, net" in out
    assert "1,234" in out
    assert "45,678" in out


def test_strip_xbrl_metadata_collapses_blank_runs() -> None:
    """Removing a metadata block shouldn't leave 3+ blank lines behind."""
    text = "Revenue\n100\nType: credit\nPeriod Type: duration\n\n\nNet income\n50"
    out = _strip_xbrl_metadata(text)
    assert "\n\n\n" not in out


def test_strip_xbrl_metadata_empty() -> None:
    assert _strip_xbrl_metadata("") == ""
