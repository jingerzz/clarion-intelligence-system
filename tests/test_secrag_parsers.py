"""Tests for ai_buffett_zo.secrag.parsers."""

from __future__ import annotations

from ai_buffett_zo.secrag.parsers import (
    detect_content_type,
    parse,
    parse_html,
    parse_text,
    parse_xml,
)


# ---- detect_content_type ---------------------------------------------------


def test_detect_html() -> None:
    assert detect_content_type("nvda-10k.htm") == "html"
    assert detect_content_type("filing.html") == "html"


def test_detect_xml() -> None:
    assert detect_content_type("form4.xml") == "xml"


def test_detect_text() -> None:
    assert detect_content_type("transcript.txt") == "text"


def test_detect_default_html_for_unknown() -> None:
    assert detect_content_type("unknown.bin") == "html"


# ---- HTML parser -----------------------------------------------------------


def test_html_parser_emits_markdown_headings() -> None:
    html = """
    <html><body>
    <h1>Annual Report</h1>
    <h2>Item 1. Business</h2>
    <p>We sell stuff.</p>
    <h2>Item 1A. Risk Factors</h2>
    <p>Stuff is risky.</p>
    </body></html>
    """
    md = parse_html(html)
    assert "# Annual Report" in md
    assert "## Item 1. Business" in md
    assert "## Item 1A. Risk Factors" in md
    assert "We sell stuff." in md
    assert "Stuff is risky." in md


def test_html_parser_strips_script_and_style() -> None:
    html = """
    <html><head>
        <script>alert('x')</script>
        <style>body { color: red; }</style>
    </head><body>
        <h2>Heading</h2>
        <p>Body text.</p>
    </body></html>
    """
    md = parse_html(html)
    assert "alert" not in md
    assert "color: red" not in md
    assert "Body text." in md


def test_html_parser_collapses_whitespace() -> None:
    html = "<html><body><p>foo    bar</p>\n\n\n\n<p>baz</p></body></html>"
    md = parse_html(html)
    assert "foo bar" in md
    assert "\n\n\n" not in md


def test_html_parser_handles_no_structure() -> None:
    """Bare text or text-only HTML still produces something searchable."""
    html = "<html><body>Just some text.</body></html>"
    md = parse_html(html)
    assert "Just some text" in md


# ---- XML parser (Form 4) ---------------------------------------------------


SAMPLE_FORM_4 = """<?xml version="1.0"?>
<ownershipDocument>
  <documentType>4</documentType>
  <periodOfReport>2026-04-30</periodOfReport>
  <issuer>
    <issuerCik>0001045810</issuerCik>
    <issuerName>NVIDIA CORPORATION</issuerName>
    <issuerTradingSymbol>NVDA</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerName>HUANG JEN-HSUN</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>1</isDirector>
      <isOfficer>1</isOfficer>
      <officerTitle>President and CEO</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle>
        <value>Common Stock</value>
      </securityTitle>
      <transactionDate>
        <value>2026-04-29</value>
      </transactionDate>
      <transactionCoding>
        <transactionCode>S</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares>
          <value>120000</value>
        </transactionShares>
        <transactionPricePerShare>
          <value>140.50</value>
        </transactionPricePerShare>
        <transactionAcquiredDisposedCode>
          <value>D</value>
        </transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction>
          <value>800000</value>
        </sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
  <footnotes>
    <footnote id="F1">10b5-1 plan adopted on 2025-12-15.</footnote>
  </footnotes>
</ownershipDocument>
"""


def test_xml_parser_form_4_header() -> None:
    md = parse_xml(SAMPLE_FORM_4)
    assert "# Form 4" in md
    assert "**Period of report:**" in md and "2026-04-30" in md


def test_xml_parser_form_4_issuer_block() -> None:
    md = parse_xml(SAMPLE_FORM_4)
    assert "## Issuer" in md
    assert "NVIDIA CORPORATION" in md
    assert "NVDA" in md
    assert "0001045810" in md


def test_xml_parser_form_4_reporting_owner_with_roles() -> None:
    md = parse_xml(SAMPLE_FORM_4)
    assert "## Reporting owner(s)" in md
    assert "HUANG JEN-HSUN" in md
    assert "Director" in md
    assert "Officer (President and CEO)" in md


def test_xml_parser_form_4_transaction_table() -> None:
    md = parse_xml(SAMPLE_FORM_4)
    assert "## Non-derivative transactions" in md
    # Transaction date + code + shares + price + post-tx + security
    assert "2026-04-29" in md
    assert "120000" in md
    assert "140.50" in md
    assert "800000" in md
    assert "Common Stock" in md
    # Disposal code
    assert "| D |" in md or " D " in md


def test_xml_parser_form_4_footnotes() -> None:
    md = parse_xml(SAMPLE_FORM_4)
    assert "## Footnotes" in md
    assert "10b5-1 plan" in md
    assert "F1" in md


def test_xml_parser_unknown_schema_falls_through() -> None:
    """Unfamiliar XML still produces something searchable, not empty."""
    weird = """<?xml version="1.0"?>
<someOtherDoc>
  <importantThing>This is text we want to keep.</importantThing>
  <stuff>more</stuff>
</someOtherDoc>"""
    md = parse_xml(weird)
    assert md
    assert "This is text we want to keep." in md


# ---- Text parser -----------------------------------------------------------


def test_text_parser_passthrough_with_h1_wrapper() -> None:
    md = parse_text("just some words\nwith two lines")
    assert md.startswith("# Filing content")
    assert "just some words" in md


def test_text_parser_preserves_existing_headings() -> None:
    md = parse_text("# Already a heading\n\nbody text\n\n## Sub\n\nmore")
    assert md.startswith("# Already a heading")
    assert "Filing content" not in md  # didn't double-wrap


# ---- Dispatcher ------------------------------------------------------------


def test_parse_dispatcher_html() -> None:
    md = parse("<html><body><h2>Heading</h2></body></html>", content_type="html")
    assert "## Heading" in md


def test_parse_dispatcher_xml() -> None:
    md = parse(SAMPLE_FORM_4, content_type="xml")
    assert "# Form 4" in md


def test_parse_dispatcher_text() -> None:
    md = parse("hello world", content_type="text")
    assert "hello world" in md


def test_parse_dispatcher_unknown_raises() -> None:
    import pytest

    with pytest.raises(ValueError, match="unsupported content_type"):
        parse("x", content_type="csv")  # type: ignore[arg-type]
