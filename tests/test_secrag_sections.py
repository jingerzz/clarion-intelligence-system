"""Tests for ai_buffett_zo.secrag.sections."""

from __future__ import annotations

import pytest

from ai_buffett_zo.secrag import (
    extract_sections,
    extract_sections_from_text,
    html_to_text,
)
from ai_buffett_zo.secrag.sections import _detect_pointer


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


# ---- Pointer detection (issue #26) ----------------------------------------


# Paraphrased sentences from real 10-K filings. Lengths match live
# measurements on cis.zo.computer's indexed filings (2026-05-20):
# - IBM/RKLB Item 7/8 pointers: 220-376 chars (canonical "incorporated by reference" phrasing)
# - KO/NVDA/INTC/FSLR/NFLX/TSLA/DECK Item 8 pointers: 37-356 chars (varied phrasing — "Refer to...", "set forth in...", page numbers)
# - Real legitimate substantive sections in the same dataset start at ~540 chars
# Detection is length-only; phrase patterns only classify the target.


KO_ITEM11_POINTER = (
    "The information required by this Item is incorporated herein by reference "
    "to the information set forth under the captions 'Executive Compensation' "
    "and 'Compensation Discussion and Analysis' in the Company's definitive "
    "Proxy Statement on Schedule 14A for the 2025 Annual Meeting of Shareowners."
)

IBM_ITEM8_POINTER = (
    "The financial statements and supplementary data required by this Item are "
    "included in the Annual Report to Stockholders filed as Exhibit 13 to this "
    "Form 10-K and are incorporated herein by reference."
)

IBM_ITEM7_POINTER = (
    "The information required by Item 7 is included in the Annual Report to "
    "Stockholders filed as Exhibit 13 of this Form 10-K, which is incorporated "
    "herein by reference."
)

# KO uses "Refer to..." phrasing — no incorporation-by-reference language
KO_ITEM8_POINTER_VARIED = (
    "Refer to 'Financial Statements and Supplementary Data' included in this "
    "report. The consolidated financial statements and accompanying notes "
    "begin on page F-1 of this Form 10-K."
)

# NVDA uses "is set forth in" phrasing — also no incorporation phrase
NVDA_ITEM8_POINTER_VARIED = (
    "The information required by this Item is set forth in our Consolidated "
    "Financial Statements and accompanying notes."
)

# INTC's Item 8 is essentially a page reference
INTC_ITEM8_POINTER_TERSE = "and Supplementary Data Pages 56-108"

SUBSTANTIVE_RISK_FACTORS = (
    "Our business is concentrated in a small number of high-value contracts; "
    "the loss of any one of them could materially impact revenue. "
    "Approximately 35 percent of total revenue in fiscal 2024 came from our "
    "top three customers. Our supply chain depends on a single fabrication "
    "partner for advanced-node manufacturing, exposing us to disruption from "
    "geopolitical events, natural disasters, or capacity constraints at that "
    "partner. We do not currently have second-source agreements in place for "
    "our highest-volume products. " * 2  # >500 chars total
)


@pytest.mark.parametrize(
    ("body", "expected_pointer", "expected_target"),
    [
        # Canonical IBM/KO cases with "incorporated by reference" phrasing
        (KO_ITEM11_POINTER, True, "def14a"),
        (IBM_ITEM8_POINTER, True, "annual_report_same_doc"),
        (IBM_ITEM7_POINTER, True, "annual_report_same_doc"),
        # Varied phrasings the canonical Zo found in real 10-Ks. Length-only
        # detection catches all of these; classification keys on what
        # pointer-language tokens are present.
        (KO_ITEM8_POINTER_VARIED, True, "unknown"),       # "Refer to..."
        (NVDA_ITEM8_POINTER_VARIED, True, "unknown"),     # "set forth in..."
        (INTC_ITEM8_POINTER_TERSE, True, "unknown"),      # "Pages 56-108"
        # Long substantive content stays clean even if it mentions
        # "incorporated by reference" in passing
        (SUBSTANTIVE_RISK_FACTORS, False, None),
        (
            "Our debt agreements contain financial covenants. "
            "The risk-weighted assets calculation methodology is incorporated "
            "herein by reference to the Basel III framework. " + "x" * 600,
            False,
            None,
        ),
        # Parser-bug cases the canonical Zo found in real 10-Ks: short
        # extractor outputs with no pointer-language tokens. These are TOC
        # fragments / orphan whitespace, not real pointers — Phase 2 should
        # skip recovery on them.
        ("and", True, "parser_bug"),                                # PWR business=3 chars
        ("3\n\nInformation about our Executive Officers\n\n14", True, "parser_bug"),  # MSFT TOC
        # "Not applicable" — also short, no pointer language → parser bug.
        # A 10-K with literally "Not applicable" in a curated section is
        # broken either way; flagging it as parser_bug is the right behavior.
        ("Not applicable.", True, "parser_bug"),
    ],
)
def test_detect_pointer_classifies_pointer_and_target(body, expected_pointer, expected_target) -> None:
    is_pointer, target = _detect_pointer(body)
    assert is_pointer is expected_pointer
    assert target == expected_target


def test_pointer_detection_propagates_to_extracted_section() -> None:
    """End-to-end: a curated 10-K extraction surfaces is_pointer_only on the right section."""
    text = (
        "Item 1. Business\n"
        + "We sell things. " * 80  # substantive
        + "\n\n"
        + "Item 1A. Risk Factors\n"
        + "Things could go wrong. " * 80  # substantive
        + "\n\n"
        + "Item 7. Management's Discussion and Analysis\n"
        + IBM_ITEM7_POINTER
        + "\n\n"
        + "Item 8. Financial Statements\n"
        + IBM_ITEM8_POINTER
        + "\n\n"
        + "Item 9. Changes in Accountants\nNone.\n"
    )
    sections = extract_sections_from_text(text)
    by_label = {s.label: s for s in sections}

    # Pointer sections flagged correctly
    assert by_label["mdna"].is_pointer_only is True
    assert by_label["mdna"].pointer_target == "annual_report_same_doc"
    assert by_label["financial_statements"].is_pointer_only is True
    assert by_label["financial_statements"].pointer_target == "annual_report_same_doc"

    # Substantive sections stay clean
    assert by_label["business"].is_pointer_only is False
    assert by_label["business"].pointer_target is None
    assert by_label["risk_factors"].is_pointer_only is False
    assert by_label["risk_factors"].pointer_target is None
