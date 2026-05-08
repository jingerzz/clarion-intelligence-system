"""HTML → markdown for SEC filings.

The conversion preserves heading structure (h1-h6 → markdown headings) which is
what `secrag/sections.py:extract_sections_generic` keys off of when extracting
top-level sections from non-10-K/10-Q filings (S-1, DEF 14A, prospectuses).

For 10-K/10-Q, the legacy regex-based extractor in `sections.py` continues to
operate on the BS4-stripped plain text — that path is preserved for back-compat
with the curated 4-section model and unchanged 10-K test fixtures.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

# Block-level tags that should produce a paragraph break in the markdown output.
_BLOCK_TAGS = {
    "p", "div", "section", "article", "li", "tr", "br",
    "blockquote", "pre", "table", "thead", "tbody", "tfoot",
}

_HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


def parse_html(content: str) -> str:
    """Convert SEC filing HTML into markdown with heading hierarchy preserved.

    Strategy:
    - h1-h6 tags → `#` to `######` markdown headings
    - p / div / li / tr / br → paragraph break
    - All other tags stripped to plain text (no markdown bold / italic / links —
      we don't need those for indexing and they add noise to keyword search)
    - Whitespace collapsed (single spaces within lines, blank-line separators)
    - Pages with no block structure (bare text in body) fall through to a full
      get_text dump so something searchable always comes out.
    """
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    body = soup.find("body") or soup

    chunks: list[str] = []
    for child in body.children:
        _walk(child, chunks)

    # Fallback: walker emitted nothing structured — emit the body's full text
    if not chunks:
        text = body.get_text(separator=" ", strip=True)
        if text:
            chunks.append(text)

    md = "".join(chunks)
    md = _normalize_whitespace(md)
    return md


def _walk(element, out: list[str]) -> None:
    """Recursive walk: emit headings as markdown, blocks as paragraphs, drop other tags."""
    name = getattr(element, "name", None)
    if name is None:
        # Bare text node — parents with block tags pick it up via get_text;
        # don't emit at this level (avoids duplication)
        return

    if name in _HEADING_TAGS:
        level = _HEADING_TAGS[name]
        text = element.get_text(strip=True)
        if text:
            out.append("\n\n" + "#" * level + " " + text + "\n\n")
        return

    if name in _BLOCK_TAGS:
        text = element.get_text(separator=" ", strip=True)
        if text:
            out.append(text + "\n\n")
        return

    # Other tag: recurse into children
    for child in element.children:
        _walk(child, out)


def _normalize_whitespace(md: str) -> str:
    """Collapse runs of whitespace within lines; cap blank-line separators at 2 newlines."""
    lines = [re.sub(r"[ \t]+", " ", line.strip()) for line in md.splitlines()]
    md = "\n".join(lines)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()
