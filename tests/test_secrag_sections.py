"""Tests for ai_buffett_zo.secrag.sections."""

from __future__ import annotations

from ai_buffett_zo.secrag import (
    extract_sections,
    extract_sections_from_text,
    html_to_text,
)


SAMPLE_10K_HTML = """
<html>
<body>
<h1>NVIDIA CORPORATION</h1>
<h2>Annual Report on Form 10-K</h2>

<p><b>Table of Contents</b></p>
<p>Item 1. Business</p>
<p>Item 1A. Risk Factors</p>
<p>Item 7. Management's Discussion and Analysis</p>

<h2>Item 1. Business</h2>
<p>NVIDIA is a computing infrastructure company. We design and sell GPUs.</p>
<p>Our platforms power gaming, data centers, and automotive.</p>

<h2>Item 1A. Risk Factors</h2>
<p>Our business depends on advanced AI accelerators from a small number of suppliers.</p>
<p>Supply constraints and export controls could materially impact our gross margins.</p>

<h2>Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations</h2>
<p>Revenue grew 50% year over year, driven by data center demand.</p>
<p>Gross margin expanded to 75%.</p>

<h2>Item 8. Financial Statements and Supplementary Data</h2>
<p>See consolidated financial statements on the following pages.</p>

<h2>Item 9. Changes in Accountants</h2>
<p>None.</p>
</body>
</html>
"""


def test_html_to_text_strips_tags_and_collapses_ws() -> None:
    html = "<html><body><p>Hello   world.</p>\n\n\n<p>Next.</p></body></html>"
    text = html_to_text(html)
    assert "Hello world." in text
    assert "Next." in text
    assert "<p>" not in text
    # No more than two consecutive newlines
    assert "\n\n\n" not in text


def test_extract_sections_finds_all_curated() -> None:
    sections = extract_sections(SAMPLE_10K_HTML)
    labels = [s.label for s in sections]
    assert labels == ["business", "risk_factors", "mdna", "financial_statements"]


def test_extract_sections_business_body() -> None:
    sections = extract_sections(SAMPLE_10K_HTML)
    business = next(s for s in sections if s.label == "business")
    assert "computing infrastructure" in business.text
    assert "gaming" in business.text


def test_extract_sections_risk_factors_body() -> None:
    sections = extract_sections(SAMPLE_10K_HTML)
    rf = next(s for s in sections if s.label == "risk_factors")
    assert "AI accelerators" in rf.text
    assert "Supply constraints" in rf.text


def test_extract_sections_picks_last_occurrence_of_header() -> None:
    """Filings include a TOC with the same headers — we should slice from the
    real section, not from the TOC."""
    sections = extract_sections(SAMPLE_10K_HTML)
    business = next(s for s in sections if s.label == "business")
    # If we'd picked the TOC occurrence, the body would include "Item 1A. Risk Factors"
    # as part of business text. With "last occurrence" rule, it shouldn't.
    assert "AI accelerators" not in business.text


def test_extract_sections_stops_at_next_item() -> None:
    """Last curated section should stop at 'Item 9. ...' even though Item 9
    is not curated."""
    sections = extract_sections(SAMPLE_10K_HTML)
    fs = next(s for s in sections if s.label == "financial_statements")
    assert "consolidated financial" in fs.text
    assert "Changes in Accountants" not in fs.text


def test_extract_sections_handles_missing_sections() -> None:
    """A 10-Q with only Risk Factors and MD&A — business and FS missing."""
    html = """
    <html><body>
    <h2>Item 1A. Risk Factors</h2>
    <p>Some risks here.</p>
    <h2>Item 7. Management's Discussion and Analysis</h2>
    <p>MD&A content.</p>
    </body></html>
    """
    sections = extract_sections(html)
    labels = [s.label for s in sections]
    assert labels == ["risk_factors", "mdna"]


def test_extract_sections_from_text_works_on_pre_normalized() -> None:
    text = (
        "Item 1. Business\nWe sell things.\n\n"
        "Item 1A. Risk Factors\nThings could go wrong.\n\n"
        "Item 7. Management's Discussion and Analysis\nWe did great.\n\n"
        "Item 8. Financial Statements\nNumbers attached."
    )
    sections = extract_sections_from_text(text)
    labels = [s.label for s in sections]
    assert labels == ["business", "risk_factors", "mdna", "financial_statements"]
    assert "We sell things" in sections[0].text


def test_section_offsets_in_doc_order() -> None:
    sections = extract_sections(SAMPLE_10K_HTML)
    starts = [s.char_start for s in sections]
    assert starts == sorted(starts)
