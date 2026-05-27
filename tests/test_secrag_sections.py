"""Tests for ai_buffett_zo.secrag.sections."""

from __future__ import annotations

from ai_buffett_zo.secrag import (
    extract_sections,
    extract_sections_from_text,
    html_to_text,
)
from ai_buffett_zo.secrag.sections import _is_toc_shaped, extract_sections_for_form


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
