"""Format-specific parsers that normalize SEC filing content into markdown.

The output is markdown-with-headings — a format the section extractor can split
on cleanly regardless of the source format. Each parser is its own module so
adding a new format (PDF, etc.) doesn't require touching the dispatcher.

Dispatcher: `parse(content, content_type)` selects the parser by content_type
("html" / "xml" / "text"). For SEC filings, use the file extension on the
primary document:
- `.htm`, `.html` → "html"
- `.xml`           → "xml" (Form 4 / 5 / 3)
- `.txt`           → "text"
"""

from __future__ import annotations

from typing import Literal

from ai_buffett_zo.secrag.parsers.html import parse_html
from ai_buffett_zo.secrag.parsers.text import parse_text
from ai_buffett_zo.secrag.parsers.xml import parse_xml

ContentType = Literal["html", "xml", "text"]


def parse(content: str, *, content_type: ContentType = "html") -> str:
    """Parse `content` into markdown with heading structure preserved."""
    if content_type == "html":
        return parse_html(content)
    if content_type == "xml":
        return parse_xml(content)
    if content_type == "text":
        return parse_text(content)
    raise ValueError(f"unsupported content_type: {content_type}")


def detect_content_type(filename: str) -> ContentType:
    """Best-effort content-type guess from a filename (or URL)."""
    name = filename.lower()
    if name.endswith((".xml",)):
        return "xml"
    if name.endswith((".htm", ".html")):
        return "html"
    if name.endswith((".txt",)):
        return "text"
    # Default to html — most SEC primary docs are HTML
    return "html"


__all__ = ["ContentType", "detect_content_type", "parse", "parse_html", "parse_text", "parse_xml"]
