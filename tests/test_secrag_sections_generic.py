"""Tests for the generic section extractor + form-aware dispatcher.

The original 10-K / 10-Q curated extractor is exercised by
test_secrag_sections.py; this file covers the new paths added in B-6b:
- extract_sections_generic (markdown heading split)
- extract_sections_for_form (routes by form type, falls back to generic)
- _slugify
- Section.label is canonical for 10-K, slug for everything else
"""

from __future__ import annotations

from ai_buffett_zo.secrag import (
    Section,
    extract_sections_for_form,
    extract_sections_generic,
)
from ai_buffett_zo.secrag.sections import _slugify


# ---- _slugify --------------------------------------------------------------


def test_slugify_basic() -> None:
    assert _slugify("Item 1A. Risk Factors") == "item-1a-risk-factors"


def test_slugify_strips_punctuation() -> None:
    assert _slugify("Liquidity & Capital Resources") == "liquidity-capital-resources"


def test_slugify_handles_empty() -> None:
    assert _slugify("") == "section"
    assert _slugify("---") == "section"


def test_slugify_collapses_whitespace() -> None:
    assert _slugify("  Foo   Bar  ") == "foo-bar"


# ---- extract_sections_generic on HTML --------------------------------------


def test_generic_html_with_h2_headings() -> None:
    html = """
    <html><body>
    <h1>S-1 Registration Statement</h1>
    <h2>Prospectus Summary</h2>
    <p>This is the summary.</p>
    <h2>Risk Factors</h2>
    <p>Some risks.</p>
    <h2>Use of Proceeds</h2>
    <p>We will use them wisely.</p>
    </body></html>
    """
    sections = extract_sections_generic(html, content_type="html")
    # Top-level heading is H1 → only "S-1 Registration Statement" is at top level
    assert len(sections) == 1
    assert sections[0].title == "S-1 Registration Statement"
    # The H2 sub-headings + body all roll up into the H1's text
    assert "Prospectus Summary" in sections[0].text
    assert "Risk Factors" in sections[0].text


def test_generic_html_with_h2_only_top_level() -> None:
    """When the document has no H1, H2 becomes the top level."""
    html = """
    <html><body>
    <h2>Section A</h2>
    <p>Body A.</p>
    <h2>Section B</h2>
    <p>Body B.</p>
    </body></html>
    """
    sections = extract_sections_generic(html, content_type="html")
    assert len(sections) == 2
    titles = [s.title for s in sections]
    assert titles == ["Section A", "Section B"]
    assert sections[0].label == "section-a"
    assert sections[1].label == "section-b"
    assert "Body A." in sections[0].text
    assert "Body B." in sections[1].text


def test_generic_no_headings_returns_filing_content() -> None:
    """A document with no headings produces a single 'filing-content' section."""
    html = "<html><body><p>Just some prose. No structure.</p></body></html>"
    sections = extract_sections_generic(html, content_type="html")
    assert len(sections) == 1
    assert sections[0].label == "filing-content"
    assert "Just some prose" in sections[0].text


# ---- extract_sections_generic on XML (Form 4) ------------------------------


SAMPLE_FORM_4 = """<?xml version="1.0"?>
<ownershipDocument>
  <documentType>4</documentType>
  <issuer><issuerName>NVIDIA</issuerName></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>JEN-HSUN HUANG</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>CEO</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
</ownershipDocument>
"""


def test_generic_xml_form_4_top_level_is_form() -> None:
    sections = extract_sections_generic(SAMPLE_FORM_4, content_type="xml")
    assert len(sections) == 1
    assert sections[0].title == "Form 4"
    assert sections[0].label == "form-4"
    assert "NVIDIA" in sections[0].text
    assert "JEN-HSUN HUANG" in sections[0].text


# ---- Section.label semantics -----------------------------------------------


def test_section_label_canonical_for_curated_10k() -> None:
    """Curated extraction (10-K) preserves canonical labels."""
    html = """
    <html><body>
    <h2>Item 1. Business</h2>
    <p>What we do.</p>
    <h2>Item 1A. Risk Factors</h2>
    <p>Risks.</p>
    </body></html>
    """
    sections = extract_sections_for_form(html, form="10-K", content_type="html")
    labels = [s.label for s in sections]
    assert "business" in labels
    assert "risk_factors" in labels


def test_section_label_slug_for_generic() -> None:
    html = """
    <html><body>
    <h2>Liquidity and Capital Resources</h2>
    <p>Cash flow detail.</p>
    </body></html>
    """
    sections = extract_sections_for_form(html, form="S-1", content_type="html")
    assert any(s.label == "liquidity-and-capital-resources" for s in sections)


# ---- extract_sections_for_form dispatcher ----------------------------------


def test_dispatcher_routes_10k_to_curated() -> None:
    """10-K with proper item headers should hit the curated path."""
    html = """
    <html><body>
    <p>Item 1. Business</p>
    <p>What we do.</p>
    <p>Item 1A. Risk Factors</p>
    <p>Stuff is risky.</p>
    </body></html>
    """
    sections = extract_sections_for_form(html, form="10-K")
    labels = [s.label for s in sections]
    # Curated returns canonical labels; generic would return slugs
    assert "business" in labels
    assert "risk_factors" in labels


def test_dispatcher_falls_back_to_generic_when_curated_finds_nothing() -> None:
    """A 10-K-typed filing with non-Item headers should fall through to generic."""
    html = """
    <html><body>
    <h2>Some Other Heading</h2>
    <p>Body text.</p>
    </body></html>
    """
    sections = extract_sections_for_form(html, form="10-K")
    assert len(sections) >= 1
    assert sections[0].label == "some-other-heading"


def test_dispatcher_routes_form_4_to_generic_xml() -> None:
    sections = extract_sections_for_form(SAMPLE_FORM_4, form="4", content_type="xml")
    assert len(sections) == 1
    assert sections[0].label == "form-4"


def test_dispatcher_routes_s1_to_generic_html() -> None:
    html = """
    <html><body>
    <h2>Prospectus Summary</h2>
    <p>Summary text.</p>
    </body></html>
    """
    sections = extract_sections_for_form(html, form="S-1", content_type="html")
    assert any(s.label == "prospectus-summary" for s in sections)


def test_dispatcher_normalizes_form_case_and_amendments() -> None:
    """`10-K/A` should still go through the curated path."""
    html = """
    <html><body>
    <p>Item 1. Business</p>
    <p>What we do.</p>
    </body></html>
    """
    sections = extract_sections_for_form(html, form="10-K/A")
    labels = [s.label for s in sections]
    assert "business" in labels


def test_section_dataclass_shape() -> None:
    """Section keeps its shape across both extraction paths."""
    sections = extract_sections_generic("# A\n\nbody\n", content_type="text")
    assert len(sections) == 1
    s = sections[0]
    assert isinstance(s, Section)
    assert hasattr(s, "label")
    assert hasattr(s, "title")
    assert hasattr(s, "text")
    assert hasattr(s, "char_start")
    assert hasattr(s, "char_end")
