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

    Pointer-only sections (those that incorporate substantive content by
    reference instead of containing it inline) are flagged so downstream
    consumers can either follow the pointer or surface the gap to the user.
    See `_detect_pointer` for the heuristic.
    """

    label: str
    title: str          # heading as it appeared in the filing
    text: str           # body text under this heading
    char_start: int     # offset in the normalized doc
    char_end: int
    is_pointer_only: bool = False         # True when body is just an "incorporated by reference" pointer
    pointer_target: str | None = None     # "def14a" | "annual_report_same_doc" | "parser_bug" | "unknown" | None
    recovered_via: str | None = None      # "filing_summary_r_files" when Phase 2 replaced the pointer with substantive content; None otherwise


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

# ---- Pointer-section detection --------------------------------------------
#
# Some 10-K sections (especially Items 7-8 and 10-14) are short pointers that
# direct the reader to substantive content elsewhere — sometimes in a
# companion DEF 14A proxy filing, sometimes later in the same primary 10-K doc
# (as "Exhibit 13" or "Annual Report"), sometimes just a page reference like
# "Pages 56-108".
#
# **Detection is length-only for curated 10-K/10-Q sections** (Items 1, 1A, 7,
# 8). Real-data sweep against 30 indexed 10-Ks (2026-05-20) showed pointer
# language is wildly varied — only 3 of 11 short pointers used the
# "incorporated by reference" phrasing. The others said "Refer to...", "see
# our Consolidated Financial Statements", "is set forth in...", or just page
# numbers. Length is the only reliable signal because curated 10-K sections
# are normally multi-page; a short body is almost always a pointer or a
# TOC-capture parser bug (both useful to flag for downstream recovery).
#
# Phrase patterns below are used purely for **classification** — once a
# section is flagged short, the patterns decide what kind of pointer it
# probably is so Phase 1/2 can pick the right recovery strategy. Phrase
# matches don't gate detection.

# Distinguishes which document the pointer points to. Annual-Report references
# are checked first because Pattern B (Items 7/8 → same-doc continuation) is
# higher severity than Pattern A (Items 10-14 → companion DEF 14A); when both
# match, the more-severe target wins.
POINTER_TARGET_ANNUAL_REPORT_RE = re.compile(
    r"annual\s+report\s+to\s+(?:stockholders|shareholders)|exhibit\s+13\b",
    re.IGNORECASE,
)
POINTER_TARGET_DEF14A_RE = re.compile(
    r"proxy\s+statement|schedule\s+14a|def\s*14a",
    re.IGNORECASE,
)

# Pointer-language markers used to distinguish "real but unrecognized pointer"
# from "parser-extraction bug." Short curated 10-K sections almost always
# contain at least one of these tokens when they're a genuine pointer
# (canonical "incorporated by reference", varied "Refer to...", "see our
# Consolidated...", "is set forth in...", or even bare "Pages 56-108"). Short
# sections WITHOUT any of these tokens are typically parser bugs — TOC
# fragments, orphan whitespace, the `ANY_ITEM_HEADER` regex anchoring on a
# table-of-contents line instead of the body. Phase 2 should skip recovery on
# those; the underlying extractor regex is tracked separately.
POINTER_LANGUAGE_RE = re.compile(
    r"\brefer\b|\bsee\b|\bincorporat(?:ed|ing)\b|\bset\s+forth\b"
    r"|\binformation\s+required\b|\bpages?\s+\d",
    re.IGNORECASE,
)

# Threshold for "section body is too short to be substantive 10-K content."
# Real Items 7-8 pointers in IBM/KO/NVDA/INTC measure 37-499 chars; real
# legitimate-content sections in the same dataset start at ~540 chars (MU
# mdna). 500 is the natural cut-line.
POINTER_BODY_MAX_CHARS = 500


def _detect_pointer(body: str) -> tuple[bool, str | None]:
    """Classify a curated 10-K section body as pointer-only or substantive.

    **Detection is length-only.** Pointer phrasing in real 10-Ks varies too
    much to use as a gate ("Refer to...", "see our Consolidated...", "is set
    forth in...", page-only references). Curated 10-K sections are normally
    multi-page; bodies under ``POINTER_BODY_MAX_CHARS`` (500) are almost
    always either pointers or parser-extraction bugs.

    Classification distinguishes the two so Phase 2 can act differently:

    - ``"annual_report_same_doc"`` — body mentions Annual Report to
      Stockholders or Exhibit 13 (Pattern B: companion-document recovery
      via FilingSummary.xml + R-files).
    - ``"def14a"`` — body mentions Proxy Statement or Schedule 14A
      (Pattern A: companion DEF 14A auto-enqueue, handled by Phase 1).
    - ``"unknown"`` — body has at least one pointer-language marker but
      doesn't match a specific target document. Phase 2 should still
      attempt FilingSummary recovery; most "unknown" cases turn out to
      be same-doc pointers using varied phrasing.
    - ``"parser_bug"`` — body has NO pointer-language markers at all.
      These are TOC fragments, orphan whitespace, or other extractor
      artifacts (e.g. PWR business="and" at 3 chars). Phase 2 should
      skip recovery; the underlying extractor regex needs separate fix.

    Returns ``(is_pointer_only, pointer_target)``. ``is_pointer_only`` is
    True iff body is shorter than the threshold; ``pointer_target`` is one
    of the four strings above or ``None`` when not a pointer.

    Only call this on curated 10-K/10-Q sections. Generic extraction (DEF
    14A, Form 4, etc.) has legitimate short sections and shouldn't be flagged.
    """
    if len(body) >= POINTER_BODY_MAX_CHARS:
        return False, None
    # Short body without any pointer-language markers → parser bug. Don't
    # let Phase 2 try to "recover" content that was never there.
    if not POINTER_LANGUAGE_RE.search(body):
        return True, "parser_bug"
    if POINTER_TARGET_ANNUAL_REPORT_RE.search(body):
        return True, "annual_report_same_doc"
    if POINTER_TARGET_DEF14A_RE.search(body):
        return True, "def14a"
    return True, "unknown"

# Form types that use the curated 10-K extraction path. All other forms use
# generic extraction.
CURATED_FORMS: frozenset[str] = frozenset({"10-K", "10-Q", "10-K/A", "10-Q/A"})


# Forms that always get LLM-summarized full tree indexing because they're long
# and structured. Mirrors the AWB/Clarion sec-rag allowlist (which itself
# mirrors the structure of SEC's primary financial filings). Anything not in
# this set takes the raw single-node fallback path unless it exceeds the token
# safety net (see RAW_INDEX_TOKEN_LIMIT in tree.py).
FULL_INDEX_FORMS: frozenset[str] = frozenset({
    "10-K", "10-Q",
    "S-1", "S-3", "S-4", "S-11",
    "20-F", "40-F",
    "DEF 14A", "DEFA14A", "DEF 14C",
    "6-K",
    "F-1", "F-3", "F-4",
    "N-CSR", "N-CSRS",
    "ARS",
})


def normalize_form(form: str) -> str:
    """Normalize a form string for allowlist comparison.

    Strips the `/A` amendment suffix and a leading `Form ` prefix so that
    `10-K/A` matches `10-K` and `Form 4` matches `4`. Whitespace-stripped and
    case-preserved (the canonical SEC form names are mixed case, e.g. `DEF 14A`).
    """
    f = (form or "").strip()
    if f.endswith("/A"):
        f = f[:-2].rstrip()
    if f.lower().startswith("form "):
        f = f[5:].lstrip()
    return f


def should_full_index(form: str | None, token_count: int, *, raw_token_limit: int = 15_000) -> bool:
    """Decide whether a filing warrants full LLM-summarized tree indexing.

    Returns True (full index) when:
    - Form type is unknown — be safe; build a tree
    - Normalized form is in FULL_INDEX_FORMS (the long-structured-filings allowlist)
    - Token count exceeds raw_token_limit (safety net for unexpectedly long
      "raw" forms, e.g. an 8-K with a long exhibit attached)

    Otherwise returns False — caller should use the raw single-node fallback.
    """
    if form is None:
        return True
    if normalize_form(form) in FULL_INDEX_FORMS:
        return True
    return token_count > raw_token_limit


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
        is_pointer, target = _detect_pointer(body)
        sections.append(
            Section(
                label=label,
                title=title_line,
                text=body,
                char_start=start,
                char_end=end,
                is_pointer_only=is_pointer,
                pointer_target=target,
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
        # No headings — return one section with the whole text. Pointer
        # detection skipped on the generic path; DEF 14A / Form 4 / 8-K
        # have legitimate short sections that the length-only detector
        # would over-flag.
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
        # Pointer detection deliberately skipped on the generic path — see the
        # docstring on `_detect_pointer`. Curated 10-K/10-Q extraction (above)
        # is the only call site.
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
