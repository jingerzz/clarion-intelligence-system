"""HTML → curated 10-K/10-Q sections.

We extract a small, opinionated set: Item 1 Business, Item 1A Risk Factors,
Item 7 MD&A, Item 8 Financial Statements. This keeps the index small and the
indexing fast. Add sections by extending CURATED_SECTIONS.

10-K/10-Q HTML layout is wildly inconsistent across filers. Strategy:
1. Strip HTML to plain text via BeautifulSoup.
2. Find canonical "Item N." headers via regex.
3. Slice text between consecutive headers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class Section:
    """One curated section from a filing."""

    label: str          # canonical key — "business", "risk_factors", etc.
    title: str          # title as it appeared in the filing
    text: str           # plain text body
    char_start: int     # offset in the normalized doc (for debugging)
    char_end: int


# Canonical label → regex finding the section header. Order matters: more
# specific patterns (e.g. 1A) are searched independently, but we sort all
# matches by document position before slicing.
#
# Patterns are case-insensitive and tolerate common typographical variants
# (period, colon, en-dash, em-dash, bare space).
CURATED_SECTIONS: dict[str, re.Pattern[str]] = {
    "business": re.compile(
        r"item\s*1\b(?!a)[\.\s\-:–—]*business\b",
        re.IGNORECASE,
    ),
    "risk_factors": re.compile(
        r"item\s*1a\b[\.\s\-:–—]*risk\s+factors\b",
        re.IGNORECASE,
    ),
    "mdna": re.compile(
        r"item\s*7\b(?!a)[\.\s\-:–—]*management.{0,80}analysis",
        re.IGNORECASE | re.DOTALL,
    ),
    "financial_statements": re.compile(
        r"item\s*8\b[\.\s\-:–—]*(?:financial\s+statements|consolidated\s+financial)",
        re.IGNORECASE,
    ),
}

# Stop-marker patterns used to bound the LAST curated section. We slice up to
# the next "Item N" header that isn't one we care about.
ANY_ITEM_HEADER = re.compile(
    r"\bitem\s*\d+[a-z]?\b[\.\s\-:–—]",
    re.IGNORECASE,
)


def html_to_text(html: str) -> str:
    """Normalize SEC filing HTML to plain text.

    - Remove <script>, <style>, hidden elements.
    - Collapse whitespace.
    - Preserve paragraph breaks as double-newlines.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    # Collapse runs of whitespace within lines, keep blank-line separators.
    lines = [re.sub(r"[ \t]+", " ", line.strip()) for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_sections(html: str) -> list[Section]:
    """Extract curated sections from a filing HTML in document order.

    Returns sections that were actually found — missing sections are silently
    skipped (10-Q filings don't have all 10-K items, for example).
    """
    text = html_to_text(html)
    return extract_sections_from_text(text)


def extract_sections_from_text(text: str) -> list[Section]:
    """Same as extract_sections but takes pre-normalized plain text.

    Useful for tests and for re-running extraction without re-parsing HTML.
    """
    # Find every curated header occurrence. Filings often repeat headers (TOC,
    # then again at the actual section). Take the LAST occurrence of each
    # canonical header — TOCs are at the front, real content is later.
    last_match: dict[str, re.Match[str]] = {}
    for label, pattern in CURATED_SECTIONS.items():
        for m in pattern.finditer(text):
            last_match[label] = m

    if not last_match:
        return []

    # Sort by start position to slice in document order.
    ordered = sorted(last_match.items(), key=lambda kv: kv[1].start())

    sections: list[Section] = []
    for i, (label, m) in enumerate(ordered):
        start = m.start()
        if i + 1 < len(ordered):
            end = ordered[i + 1][1].start()
        else:
            end = _find_section_end(text, after=m.end())
        body = text[m.end():end].strip()
        title_line = text[m.start():m.end()].strip()
        sections.append(
            Section(
                label=label,
                title=title_line,
                text=body,
                char_start=start,
                char_end=end,
            )
        )
    return sections


def _find_section_end(text: str, *, after: int) -> int:
    """Find the next 'Item N' header after `after`, or end of text."""
    for m in ANY_ITEM_HEADER.finditer(text, pos=after):
        return m.start()
    return len(text)
