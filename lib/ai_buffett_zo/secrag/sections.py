"""Section extraction from SEC filings.

Two extraction paths:

1. **Curated** (10-K / 10-Q) — `extract_sections(html)` finds the four canonical
   sections (Business, Risk Factors, MD&A, Financial Statements) by regex on
   the rendered text. This is the original heuristic and remains the default
   for 10-K/10-Q because filings with bold-only headings don't always render
   into proper markdown headings.

2. **Generic** (S-1, DEF 14A, Form 4, anything else) —
   `extract_sections_generic(content, content_type)` runs the content through
   a parser → markdown → splits on top-level markdown headings. Each top-level
   heading becomes one Section with a slugified label.

`extract_sections_for_form(content, form, content_type)` dispatches by form:
10-K/10-Q → curated, with generic as a safety-net fallback when curated finds
nothing; everything else → generic directly.

Form 4 / 5 / 3 are XML, not HTML — pass `content_type="xml"` and the parser
emits a structured markdown report (issuer, reporting owner(s), transaction
table) so the indexed text is keyword-searchable for insider activity queries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from ai_buffett_zo.secrag.parsers import ContentType, parse


@dataclass(frozen=True)
class Section:
    """One section from a filing.

    `label` is one of:
    - A canonical 10-K name: "business" | "risk_factors" | "mdna" | "financial_statements"
    - A slug derived from the heading title (for generic extraction):
      "prospectus-summary" | "form-4" | "executive-compensation" | etc.
    """

    label: str
    title: str          # heading as it appeared in the filing
    text: str           # body text under this heading
    char_start: int     # offset in the normalized doc
    char_end: int


# ---- Curated 10-K / 10-Q paths --------------------------------------------


# Canonical label → regex matching the section header in rendered text.
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

# Bound for the last curated section: stop at the next "Item N" header.
ANY_ITEM_HEADER = re.compile(
    r"\bitem\s*\d+[a-z]?\b[\.\s\-:–—]",
    re.IGNORECASE,
)

# Form types that use the curated 10-K extraction path. All other forms use
# generic extraction.
CURATED_FORMS: frozenset[str] = frozenset({"10-K", "10-Q", "10-K/A", "10-Q/A"})


def html_to_text(html: str) -> str:
    """Normalize HTML to plain text. Used by the curated extractor."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [re.sub(r"[ \t]+", " ", line.strip()) for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_sections(html: str) -> list[Section]:
    """Curated extraction for 10-K / 10-Q HTML. Returns sections in doc order."""
    return extract_sections_from_text(html_to_text(html))


def extract_sections_from_text(text: str) -> list[Section]:
    """Curated extraction from pre-normalized text. See `extract_sections`."""
    last_match: dict[str, re.Match[str]] = {}
    for label, pattern in CURATED_SECTIONS.items():
        for m in pattern.finditer(text):
            last_match[label] = m

    if not last_match:
        return []

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
    for m in ANY_ITEM_HEADER.finditer(text, pos=after):
        return m.start()
    return len(text)


# ---- Generic extraction (any form) ----------------------------------------


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def extract_sections_generic(
    content: str,
    *,
    content_type: ContentType = "html",
) -> list[Section]:
    """Generic extraction: any filing → markdown → split on top-level headings.

    Top-level = the shallowest heading level present in the document. For most
    SEC HTML filings that's H2; for Form 4 XML reports it's the H1 emitted by
    the parser; for arbitrary docs it's whatever the source uses.

    A filing with no headings produces a single Section with the entire text
    and a label like "filing-content".
    """
    markdown = parse(content, content_type=content_type)
    return _split_markdown_top_level(markdown)


def _split_markdown_top_level(markdown: str) -> list[Section]:
    """Split markdown on its top-level (shallowest) heading level."""
    matches = list(_HEADING_RE.finditer(markdown))
    if not matches:
        # No headings — return one section with the whole text
        return [
            Section(
                label="filing-content",
                title="Filing content",
                text=markdown.strip(),
                char_start=0,
                char_end=len(markdown),
            )
        ]

    # Top-level = the shallowest heading level present (typically 1 or 2)
    top_level = min(len(m.group(1)) for m in matches)
    top_matches = [m for m in matches if len(m.group(1)) == top_level]

    sections: list[Section] = []
    for i, m in enumerate(top_matches):
        title = m.group(2).strip()
        start = m.end()
        end = top_matches[i + 1].start() if i + 1 < len(top_matches) else len(markdown)
        body = markdown[start:end].strip()
        if not title and not body:
            continue
        sections.append(
            Section(
                label=_slugify(title),
                title=title,
                text=body,
                char_start=m.start(),
                char_end=end,
            )
        )
    return sections


def _slugify(title: str) -> str:
    """Convert a heading title to a kebab-case label safe for use as a section key."""
    if not title:
        return "section"
    s = title.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "section"


# ---- Form-aware dispatcher ------------------------------------------------


def extract_sections_for_form(
    content: str,
    *,
    form: str,
    content_type: ContentType | None = None,
) -> list[Section]:
    """Route to the right extractor based on form type.

    - 10-K / 10-Q (and amendments): curated extraction; falls back to generic
      if curated finds nothing (defensive — handles filings with non-standard
      "Item" markers)
    - Everything else (S-1, DEF 14A, Form 4, 8-K, ...): generic extraction
    - `content_type` defaults: HTML for the curated path; HTML for generic
      unless the caller passes "xml" / "text"
    """
    form_normalized = form.strip().upper()

    if form_normalized in CURATED_FORMS:
        sections = extract_sections(content) if content_type in (None, "html") else []
        if sections:
            return sections
        # Fall through to generic if curated couldn't find anything
        return extract_sections_generic(content, content_type=content_type or "html")

    return extract_sections_generic(content, content_type=content_type or "html")
