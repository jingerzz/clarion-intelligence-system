"""Tests for ai_buffett_zo.secrag.sections."""

from __future__ import annotations

import pytest

from ai_buffett_zo.secrag import (
    extract_sections,
    extract_sections_from_text,
    html_to_text,
)
from ai_buffett_zo.secrag.sections import (
    _detect_pointer,
    _is_inline_cross_reference,
    _is_section_body_start,
    _is_toc_shaped,
    _select_header_match,
    extract_sections_for_form,
)
from ai_buffett_zo.secrag.sections import CURATED_SECTIONS


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


# ---- TOC-aware extraction (issue #32) -------------------------------------


# Real-data sample: SYF 10-K (paraphrased structure). The TOC at the start
# matches the curated regex for "Item 1. Business" etc., but the body uses
# a different heading format that the regex doesn't catch (e.g., the body
# heading reads "Item 1. Description of Business" — extra "Description of"
# word that doesn't fit the `[\.\s\-:–—]*business\b` regex). Without the
# TOC-aware retry, the curated extractor returns sections whose body is
# just page references.

_SYF_STYLE_TOC_TEXT = (
    "SYNCHRONY FINANCIAL\n"
    "\n"
    "Form 10-K\n"
    "\n"
    "Table of Contents\n"
    "\n"
    "Item 1. Business 8 - 24\n"
    "Item 1A. Risk Factors 25 - 50\n"
    "Item 7. Management's Discussion and Analysis 53 - 80\n"
    "Item 8. Financial Statements and Supplementary Data 80 - 85, 88 - 97\n"
    "\n"
    # Just the TOC — no PART I, no body headings the regex can find.
    # This is the pathological case where smart retry has no anchor to use.
)

_SYF_STYLE_WITH_PART_I_AND_BODY = (
    "SYNCHRONY FINANCIAL\n"
    "\n"
    "Form 10-K\n"
    "\n"
    "Table of Contents\n"
    "\n"
    "Item 1. Business 8 - 24\n"
    "Item 1A. Risk Factors 25 - 50\n"
    "Item 7. Management's Discussion and Analysis 53 - 80\n"
    "Item 8. Financial Statements and Supplementary Data 80 - 85, 88 - 97\n"
    "\n"
    "PART I\n"
    "\n"
    "Item 1. Business\n"
    + ("We are a premier consumer financial services company. " * 30) + "\n"
    "\n"
    "Item 1A. Risk Factors\n"
    + ("Our business is subject to various risks and uncertainties. " * 30) + "\n"
    "\n"
    "Item 7. Management's Discussion and Analysis of Financial Condition\n"
    + ("Revenue increased 8% year over year. " * 30) + "\n"
    "\n"
    "Item 8. Financial Statements and Supplementary Data\n"
    + ("Total revenue: $18.5 billion. Net income: $3.2 billion. " * 30) + "\n"
)


# ---- _is_toc_shaped --------------------------------------------------------


def test_is_toc_shaped_pure_page_references() -> None:
    """The SYF symptom: body is literally just page ranges + separators."""
    assert _is_toc_shaped("8 - 24 , 80 - 85 , 88 - 97") is True
    assert _is_toc_shaped("8 - 24") is True
    assert _is_toc_shaped("103 - 150") is True


def test_is_toc_shaped_high_digit_density() -> None:
    """Page-reference patterns mixed with brief item labels are still TOC."""
    assert _is_toc_shaped("Item 1A 25 - 50") is True


def test_is_toc_shaped_substantive_body_returns_false() -> None:
    """A real section body is mostly prose, not digits."""
    assert _is_toc_shaped("We are a global technology company. " * 5) is False
    assert _is_toc_shaped(
        "Our business is concentrated in cloud infrastructure. "
        "Revenue grew 15% to $50 billion."
    ) is False


def test_is_toc_shaped_pointer_text_returns_false() -> None:
    """Issue #26 pointer-only sections aren't TOC — they're real prose."""
    assert _is_toc_shaped(
        "The information required by this Item is included in the Annual "
        "Report to Stockholders filed as Exhibit 13."
    ) is False
    assert _is_toc_shaped("Refer to 'Financial Statements and Supplementary Data' in this report.") is False


def test_is_toc_shaped_short_substantive_returns_false() -> None:
    """A short but substantive body ('Not applicable') isn't TOC."""
    assert _is_toc_shaped("Not applicable.") is False


def test_is_toc_shaped_long_body_never_toc() -> None:
    """Bodies > 500 chars are always substantive — TOC fragments are bounded."""
    long_with_digits = "0123456789 " * 100  # > 500 chars, digit-heavy
    assert _is_toc_shaped(long_with_digits) is False


def test_is_toc_shaped_empty() -> None:
    assert _is_toc_shaped("") is False
    assert _is_toc_shaped("   \n  \n  ") is False


# ---- extract_sections_from_text TOC-aware retry ---------------------------


def test_extract_returns_empty_when_only_toc_matches_and_no_part_i_anchor() -> None:
    """SYF-style pathology with no PART I to retry from → signal failure.

    The caller (extract_sections_for_form) treats an empty result as
    extraction failure and falls back to generic extraction.
    """
    sections = extract_sections_from_text(_SYF_STYLE_TOC_TEXT)
    assert sections == []


def test_extract_smart_retry_finds_body_after_part_i_anchor() -> None:
    """When the TOC matches but PART I sits before substantive bodies, retry
    starting from PART I finds the real section headings."""
    sections = extract_sections_from_text(_SYF_STYLE_WITH_PART_I_AND_BODY)

    labels = [s.label for s in sections]
    assert "business" in labels
    assert "risk_factors" in labels

    # Bodies should now be substantive prose, not page references
    business = next(s for s in sections if s.label == "business")
    assert "premier consumer financial services" in business.text
    assert _is_toc_shaped(business.text) is False


def test_extract_for_form_falls_back_to_generic_on_toc_failure() -> None:
    """End-to-end: extract_sections_for_form should fall back to generic
    when curated extraction returns [] due to TOC-only matches."""
    # Markdown-style content with a clear heading so generic extraction has
    # something to find. The curated regex anchored on the TOC entries above.
    text = _SYF_STYLE_TOC_TEXT + "\n\n## Some heading\n\nSome substantive content."
    # Convert to HTML so we exercise the html-path of extract_sections_for_form
    html = f"<html><body><pre>{text}</pre></body></html>"
    sections = extract_sections_for_form(html, form="10-K", content_type="html")
    # We should get SOMETHING — either generic-extracted sections or at least
    # the fallback single-section produced by _split_markdown_top_level.
    assert sections, "expected fallback to generic extraction when curated finds only TOC"


def test_extract_normal_10k_unaffected_by_toc_retry() -> None:
    """Regression guard: a normal 10-K with real body headings still works.

    SAMPLE_10K_HTML has clean body headings (no separate TOC), so the
    first-pass curated regex succeeds and the retry path never fires.
    """
    sections = extract_sections(SAMPLE_10K_HTML)
    labels = [s.label for s in sections]
    assert "business" in labels
    assert "risk_factors" in labels
    # Bodies are substantive
    business = next(s for s in sections if s.label == "business")
    assert _is_toc_shaped(business.text) is False


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


# ---- cross-reference / TOC anchor selection (issue #51) ---------------------

# A synthetic 10-K with the three impostor occurrences of "Item 1A. Risk
# Factors": the TOC entry (page number), the real body header (substantive
# prose), and an in-body MD&A cross-reference. The extractor must anchor on the
# body header — not the TOC (old TOC failure) and not the cross-reference (the
# old last-match-wins overshoot that put MD&A text in risk_factors).
_DOC_WITH_CROSS_REFS = """Table of Contents

Item 1. Business 3
Item 1A. Risk Factors 24
Item 1B. Unresolved Staff Comments 40
Item 7. Management's Discussion and Analysis 55
Item 8. Financial Statements 80

PART I

Item 1. Business

We design and manufacture widgets and sell them to a global base of customers
across many industries, competing on quality, scale, and an integrated software
ecosystem that we have built over many years.

Item 1A. Risk Factors

The following risk factors could materially and adversely affect our business,
financial condition, and results of operations. You should carefully consider
each of them together with the other information in this report before investing.

Item 1B. Unresolved Staff Comments

None.

PART II

Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations

Our revenue grew during the period. For additional detail on competitive and
regulatory pressures, see Item 1A. Risk Factors for additional information
regarding our investments and operations during fiscal year 2026 and beyond.

Item 8. Financial Statements

The consolidated financial statements are set forth on the pages that follow and
include the balance sheet, income statement, and statement of cash flows for each
of the periods presented in this annual report.
"""


def test_risk_factors_anchors_on_body_header_not_cross_reference() -> None:
    sections = extract_sections_from_text(_DOC_WITH_CROSS_REFS)
    by = {s.label: s for s in sections}
    rf = by["risk_factors"]
    # Body header wins: starts with the real risk-factors prose...
    assert rf.text.startswith("The following risk factors could materially")
    # ...not the MD&A cross-reference text that the old last-match rule grabbed.
    assert "Our revenue grew" not in rf.text
    assert "for additional information regarding our investments" not in rf.text


def test_mdna_anchors_past_toc_to_body_header() -> None:
    sections = extract_sections_from_text(_DOC_WITH_CROSS_REFS)
    by = {s.label: s for s in sections}
    assert by["mdna"].text.startswith("of Financial Condition and Results of Operations")
    assert "Our revenue grew during the period" in by["mdna"].text


def test_is_inline_cross_reference_detects_prose_prefix() -> None:
    text = "...see Item 1A. Risk Factors for more.\nItem 1A. Risk Factors\nbody"
    pat = CURATED_SECTIONS["risk_factors"]
    matches = list(pat.finditer(text))
    assert len(matches) == 2
    assert _is_inline_cross_reference(text, matches[0]) is True   # embedded in prose
    assert _is_inline_cross_reference(text, matches[1]) is False  # begins its line


def test_is_inline_cross_reference_allows_part_prefix() -> None:
    text = "PART I Item 1A. Risk Factors\nbody"
    m = CURATED_SECTIONS["risk_factors"].search(text)
    assert m is not None
    assert _is_inline_cross_reference(text, m) is False


def test_is_section_body_start_rejects_toc_and_cross_ref_shapes() -> None:
    assert _is_section_body_start("24\nItem 1B. Unresolved Staff Comments") is False  # TOC page#
    assert _is_section_body_start('" of this Annual Report on Form 10-K. ' * 5) is False  # quote tail
    assert _is_section_body_start(": Operational and Other Factors -- Cybersecurity") is False
    assert _is_section_body_start("x") is False  # too short
    assert _is_section_body_start(
        "The following risk factors could materially and adversely affect our "
        "business and financial condition and results of operations going forward."
    ) is True


def test_select_header_match_falls_back_to_last_when_no_body_header() -> None:
    # Only a TOC-style occurrence exists (mirrors MSFT/SYF: body header not
    # separately matchable). Selection must not crash — it falls back to the
    # last match rather than dropping the section.
    text = "Item 1A. Risk Factors 16\nItem 1B. Unresolved Staff Comments 30\n"
    matches = list(CURATED_SECTIONS["risk_factors"].finditer(text))
    assert len(matches) == 1
    assert _select_header_match(text, matches) is matches[-1]


# ---- Quarterly (10-Q) item numbering ---------------------------------------

# A 10-Q numbers MD&A as Item 2 and the financial statements as Item 1. Running
# the 10-K map (Items 7 and 8) over one matched neither, so every 10-Q indexed
# with only the Item 1A risk-factors stub — which in a 10-Q is usually the
# one-line "no material changes since the 10-K" cross-reference.
SAMPLE_10Q_HTML = """
<html>
<body>
<h1>UTILITY HOLDINGS INC.</h1>
<h2>Quarterly Report on Form 10-Q</h2>

<p><b>Table of Contents</b></p>
<p>Item 1. Financial Statements 3</p>
<p>Item 2. Management's Discussion and Analysis 16</p>
<p>Item 1A. Risk Factors 42</p>

<p>PART I</p>

<h2>Item 1. Financial Statements</h2>
<p>The accompanying unaudited consolidated financial statements have been
prepared in accordance with generally accepted accounting principles for
interim financial information and with the instructions to Form 10-Q.</p>

<h2>Item 2. Management's Discussion and Analysis of Financial Condition and Results of Operations</h2>
<p>Operating revenue increased 8.4% for the quarter, driven by a rate order
authorizing a 9.90% return on equity effective March 2026. We now expect
full-year operating earnings per share at the upper end of our guidance range.</p>

<p>PART II</p>

<h2>Item 1A. Risk Factors</h2>
<p>There have been no material changes to the risk factors previously disclosed
in our Annual Report on Form 10-K for the year ended December 31, 2025.</p>
</body>
</html>
"""


def test_quarterly_form_extracts_mdna_and_financials() -> None:
    """A 10-Q's Item 2 MD&A and Item 1 financials must both be captured."""
    sections = extract_sections_for_form(SAMPLE_10Q_HTML, form="10-Q")
    by_label = {s.label: s for s in sections}

    assert "mdna" in by_label, "10-Q MD&A (Item 2) was not extracted"
    assert "financial_statements" in by_label
    assert "9.90% return on equity" in by_label["mdna"].text
    assert "unaudited consolidated financial statements" in (
        by_label["financial_statements"].text
    )
    # The risk-factors stub is still found, and is still just the cross-reference.
    assert "no material changes" in by_label["risk_factors"].text


def test_annual_map_would_miss_quarterly_mdna() -> None:
    """Regression guard: the 10-K numbering finds no MD&A in a 10-Q.

    This is the exact failure that left AEP/DTE/FE/CMS 10-Qs holding only a
    risk-factors stub.
    """
    text = html_to_text(SAMPLE_10Q_HTML)
    assert CURATED_SECTIONS["mdna"].search(text) is None
    assert CURATED_SECTIONS["financial_statements"].search(text) is None


def test_quarterly_amendment_uses_quarterly_map() -> None:
    sections = extract_sections_for_form(SAMPLE_10Q_HTML, form="10-Q/A")
    assert "mdna" in {s.label for s in sections}


def test_annual_filing_still_uses_annual_map() -> None:
    """The 10-K path is unchanged — Item 7 MD&A, Item 1 Business."""
    sections = extract_sections_for_form(SAMPLE_10K_HTML, form="10-K")
    labels = {s.label for s in sections}
    assert "mdna" in labels
    assert "business" in labels


def test_quarterly_part_ii_item_1_does_not_capture_legal_proceedings() -> None:
    """Part I "Item 1. Financial Statements" must not collide with Part II
    "Item 1. Legal Proceedings" — the pattern requires the section name."""
    html = SAMPLE_10Q_HTML.replace(
        "<h2>Item 1A. Risk Factors</h2>",
        "<h2>Item 1. Legal Proceedings</h2>\n<p>We are party to routine litigation.</p>\n<h2>Item 1A. Risk Factors</h2>",
    )
    sections = extract_sections_for_form(html, form="10-Q")
    fs = next(s for s in sections if s.label == "financial_statements")
    assert "routine litigation" not in fs.text


# ---- Foreign annual (20-F) item numbering -----------------------------------

# A 20-F numbers Risk Factors under Item 3 (Key Information), Business as Item 4
# and MD&A as Item 5, and keeps the financial statements in an unnumbered F-page
# block after Item 19. None of that matched either curated map, so 20-Fs fell
# through to generic extraction — which splits on markdown headings and, because
# EDGAR renders a "Table of Contents" link in every page header, produced several
# hundred sections all labelled `table-of-contents`. VIST's three annual reports
# each carried ~500KB of indexed text that no MD&A or financials search reached.
#
# The fixture reproduces the two shapes that broke the first draft of the fix:
# a bare "ITEM n." heading whose title sits on the next line, and 20-F-style
# citations that name the full section path ("Item 5—Operating and Financial
# Review and Prospects—Operating Results") on their own line in the front
# matter, hundreds of thousands of characters ahead of the real heading.
SAMPLE_20F_HTML = """
<html>
<body>
<p>Table of Contents</p>
<p>Item 3.</p><p>Key Information</p>
<p>Item 4.</p><p>Information on the Company</p>
<p>Item 5.</p><p>Operating and Financial Review and Prospects</p>
<p>Item 18.</p><p>Financial Statements</p>

<p>Unless otherwise stated, production figures are presented as described under
&#8220;<i>Item 4&#8212;Information on the Company</i>.&#8221;</p>
<p>Reserve estimates follow the methodology described under
&#8220;<i>Item 5&#8212;Operating and Financial Review and Prospects&#8212;Operating Results</i>.&#8221;</p>
<p>This annual report includes market share and ranking data drawn from
independent industry publications, none of which has been independently
verified by us, and which we present solely for context.</p>

<p><b>ITEM&#8201;3.</b></p>
<p><b>KEY INFORMATION</b></p>
<p>Capitalization and Indebtedness</p>
<p>Not applicable.</p>
<p><b>RISK FACTORS</b></p>
<p>Argentine price controls on crude oil could reduce our realized prices and
materially affect our results of operations, as further described under
&#8220;<i>Item 4&#8212;Information on the Company&#8212;Industry and Regulatory Overview</i>.&#8221;</p>

<p><b>ITEM&#8201;4.</b></p>
<p><b>INFORMATION ON THE COMPANY</b></p>
<p>We hold concessions across 168,000 net acres in the Vaca Muerta shale play
and operate our own gathering and treatment infrastructure in Argentina.</p>

<p><b>ITEM&#8201;5.</b></p>
<p><b>OPERATING AND FINANCIAL REVIEW AND PROSPECTS</b></p>
<p>Total production rose to 105.4 thousand boe/d, and lifting cost per boe fell
to $4.20 from $4.70, driven by scale in our operated development areas.</p>

<p><b>ITEM&#8201;18.</b></p>
<p><b>FINANCIAL STATEMENTS</b></p>
<p>Our Audited Financial Statements are included in this annual report
beginning on page F-1.</p>

<p><b>ITEM&#8201;19.</b></p>
<p><b>EXHIBITS</b></p>
<p>Omitted from the exhibits filed with this annual report are certain
instruments and agreements with respect to long-term debt.</p>

<p><b>INDEX TO THE FINANCIAL STATEMENTS</b></p>
<p>Consolidated financial statements as of December 31, 2025 and 2024, together
with the report of the independent registered public accounting firm, are
presented in accordance with IFRS as issued by the IASB.</p>
<p>Consolidated Statement of Financial Position. Consolidated Statements of
Profit or Loss and Other Comprehensive Income. Consolidated Statement of
Changes in Equity. Consolidated Statement of Cash Flows. Notes to the
Consolidated Financial Statements: basis of preparation, material accounting
policies, segment information, revenue from contracts with customers, oil and
gas properties, impairment testing, borrowings, financial instruments and fair
value measurement, income tax, related party transactions, commitments and
contingencies, and subsequent events.</p>
</body>
</html>
"""


def test_foreign_annual_extracts_all_four_sections() -> None:
    """A 20-F's Items 3 / 4 / 5 and its F-page block must all be captured."""
    sections = extract_sections_for_form(SAMPLE_20F_HTML, form="20-F")
    by_label = {s.label: s for s in sections}

    assert set(by_label) == {
        "risk_factors",
        "business",
        "mdna",
        "financial_statements",
    }
    assert "Argentine price controls" in by_label["risk_factors"].text
    assert "168,000 net acres" in by_label["business"].text
    assert "105.4 thousand boe/d" in by_label["mdna"].text
    assert "IFRS as issued by the IASB" in by_label["financial_statements"].text


def test_foreign_annual_ignores_front_matter_citations() -> None:
    """Citations naming a section path must not win over the real heading.

    VIST's 2025 and 2026 20-Fs open with "see Item 4—Information on the
    Company." and "…Item 5—Operating and Financial Review and Prospects—
    Operating Results." Each renders on its own line and is followed by long
    prose, so neither the standalone-line test nor the substantive-body test
    rejected them: `business` and `mdna` anchored on the front matter and
    `risk_factors` swallowed 847KB of the filing.
    """
    sections = extract_sections_for_form(SAMPLE_20F_HTML, form="20-F")
    by_label = {s.label: s for s in sections}

    assert "market share and ranking data" not in by_label["business"].text
    assert "market share and ranking data" not in by_label["mdna"].text
    # risk_factors ends where business begins, rather than absorbing it
    assert "168,000 net acres" not in by_label["risk_factors"].text


def test_foreign_annual_financials_skip_the_item_18_pointer() -> None:
    """Item 18 points at the F-pages; the section must hold the F-pages."""
    sections = extract_sections_for_form(SAMPLE_20F_HTML, form="20-F")
    fs = next(s for s in sections if s.label == "financial_statements")
    assert "beginning on page F-1" not in fs.text
    assert not fs.is_pointer_only


def test_annual_map_would_miss_foreign_annual_sections() -> None:
    """Regression guard: the 10-K numbering finds nothing in a 20-F.

    This is the exact failure that left VIST's three 20-Fs indexed as a wall of
    `table-of-contents` sections with no reachable MD&A or financials.
    """
    text = html_to_text(SAMPLE_20F_HTML)
    assert CURATED_SECTIONS["mdna"].search(text) is None
    assert CURATED_SECTIONS["business"].search(text) is None


def test_foreign_annual_amendment_uses_foreign_map() -> None:
    sections = extract_sections_for_form(SAMPLE_20F_HTML, form="20-F/A")
    assert "mdna" in {s.label for s in sections}


def test_foreign_annual_accepts_filer_specific_item_4_title() -> None:
    """Shopify's 20-F heads Item 4 "Information on Shopify", not "the Company"."""
    html = SAMPLE_20F_HTML.replace(
        "<p><b>INFORMATION ON THE COMPANY</b></p>",
        "<p><b>INFORMATION ON SHOPIFY</b></p>",
    )
    sections = extract_sections_for_form(html, form="20-F")
    business = next(s for s in sections if s.label == "business")
    assert "168,000 net acres" in business.text


def test_foreign_annual_accepts_plural_reviews_in_item_5_title() -> None:
    """TSM titles Item 5 "Operating and Financial *Reviews* and Prospects"."""
    html = SAMPLE_20F_HTML.replace(
        "<p><b>OPERATING AND FINANCIAL REVIEW AND PROSPECTS</b></p>",
        "<p><b>OPERATING AND FINANCIAL REVIEWS AND PROSPECTS</b></p>",
    )
    sections = extract_sections_for_form(html, form="20-F")
    mdna = next(s for s in sections if s.label == "mdna")
    assert "105.4 thousand boe/d" in mdna.text


def test_quoted_citation_tail_is_not_a_section_body() -> None:
    """A body opening `.”` is a citation tail, not a real section body."""
    assert not _is_section_body_start('.” ' + "x" * 300)
    # A leading period on its own still marks a real header ("Risk Factors.\n…")
    assert _is_section_body_start(". " + "x" * 300)
