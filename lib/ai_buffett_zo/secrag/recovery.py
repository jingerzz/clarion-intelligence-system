"""Phase 2 recovery: replace pointer-only Items 7/8 with substantive content.

When Phase 0 flags a 10-K section as `is_pointer_only=True` with a recoverable
target (annual_report_same_doc / unknown), this module fetches the SEC's
`FilingSummary.xml` manifest at the accession root and the rendered statement
R-files (`R3.htm`, `R4.htm`, etc.) listed under `MenuCategory="Statements"`.
The recovered text replaces the section's pointer body. The original pointer
flag (`is_pointer_only=True`) is preserved for provenance; a new
`recovered_via="filing_summary_r_files"` field marks the substitution.

Caching: the manifest and each R-file are persisted under the accession's
storage dir (`{ticker}/{accession}.filing_summary.xml.gz`,
`{ticker}/{accession}.rfiles/R{n}.htm.gz`). Re-runs hit the cache; only the
first index of a given filing actually fetches from SEC.

Fallbacks:
- Pre-iXBRL filings (~pre-2012) won't have FilingSummary.xml. The fetch
  returns None; sections stay as pointers with `recovered_via=None`. The
  query layer can still surface "this section is a pointer" via
  `is_pointer_only`.
- HTTP errors other than 404 propagate up — the indexer wraps the call in a
  try/except and logs failures, so a single failed recovery doesn't break
  the rest of the indexing pipeline.

Public entry point: ``recover_pointer_sections(metadata, sections, sec_root)``.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from pathlib import Path

from ai_buffett_zo.secrag.loader import (
    FilingMetadata,
    FilingSummary,
    _parse_filing_summary,
    fetch_filing_summary_raw,
    fetch_r_file,
)
from ai_buffett_zo.secrag.sections import Section, html_to_text
from ai_buffett_zo.secrag.storage import (
    load_filing_summary,
    load_r_file,
    save_filing_summary,
    save_r_file,
)

logger = logging.getLogger(__name__)

# Labels and pointer targets where Phase 2 recovery is appropriate. Phase 1
# (Pattern A — companion DEF 14A auto-enqueue) handles `def14a` separately.
#
# `parser_bug` is included after real-data validation on cis.zo.computer
# (PR #29 review, 2026-05-22): KO's Item 8 was getting classified as
# `parser_bug` because the curated regex trimmed the "Refer to" prefix off
# its pointer text, leaving a body with no pointer-language tokens.
# Excluding `parser_bug` from recovery meant KO got no fix despite having a
# valid FilingSummary. True parser bugs (PWR business="and", MSFT TOC
# fragments) also flow through, but FilingSummary recovery degrades
# gracefully when no manifest exists or no Statements reports are listed —
# so attempting recovery on parser_bug is safe and meaningfully improves
# coverage.
RECOVERABLE_LABELS: frozenset[str] = frozenset({"mdna", "financial_statements"})
RECOVERABLE_TARGETS: frozenset[str] = frozenset({
    "annual_report_same_doc",
    "unknown",
    "parser_bug",
})

# Marker stored on recovered sections so downstream consumers (eval skill,
# audit tools) can tell that the substantive text was assembled from R-files
# rather than the original primary-doc extraction.
RECOVERED_VIA_FILING_SUMMARY = "filing_summary_r_files"


def is_recoverable(section: Section) -> bool:
    """Is this section a Phase 2 recovery candidate?"""
    return (
        section.is_pointer_only
        and section.label in RECOVERABLE_LABELS
        and section.pointer_target in RECOVERABLE_TARGETS
    )


def recover_pointer_sections(
    metadata: FilingMetadata,
    sections: list[Section],
    sec_root: Path,
) -> list[Section]:
    """Replace pointer-only Items 7/8 with substantive content from R-files.

    Returns a new list of sections — unmodified entries pass through as-is.
    For each recoverable pointer section, the returned entry has:

    - ``text``: concatenated text of every `MenuCategory="Statements"` R-file
      in the filing's manifest, with each statement prefixed by its
      ``ShortName`` header (e.g. ``"# CONSOLIDATED INCOME STATEMENT"``).
    - ``is_pointer_only``: still True (preserves provenance — section was
      originally a pointer).
    - ``recovered_via``: ``"filing_summary_r_files"``.

    On any failure path (no FilingSummary, empty Statements list, fetch
    error), the section is returned unchanged. Callers should NOT assume
    recovery succeeded; they can check ``recovered_via is not None``.
    """
    if not any(is_recoverable(s) for s in sections):
        return sections

    summary = _get_or_fetch_summary(metadata, sec_root)
    if summary is None:
        logger.info(
            "Phase 2 recovery skipped: no FilingSummary.xml for %s %s",
            metadata.ticker, metadata.accession,
        )
        return sections

    statements = summary.statements()
    if not statements:
        logger.info(
            "Phase 2 recovery skipped: no Statements reports in FilingSummary for %s %s",
            metadata.ticker, metadata.accession,
        )
        return sections

    recovered_text = _assemble_recovered_text(metadata, statements, sec_root)
    if not recovered_text:
        logger.warning(
            "Phase 2 recovery: all R-file fetches failed for %s %s",
            metadata.ticker, metadata.accession,
        )
        return sections

    out: list[Section] = []
    for s in sections:
        if is_recoverable(s):
            out.append(
                dataclasses.replace(
                    s,
                    text=recovered_text,
                    recovered_via=RECOVERED_VIA_FILING_SUMMARY,
                )
            )
        else:
            out.append(s)
    logger.info(
        "Phase 2 recovery applied to %s %s: %d statements, %d chars",
        metadata.ticker, metadata.accession,
        len(statements), len(recovered_text),
    )
    return out


def _get_or_fetch_summary(
    metadata: FilingMetadata,
    sec_root: Path,
) -> FilingSummary | None:
    """Return parsed FilingSummary, hitting the local cache before SEC.

    Cache miss → one HTTP fetch, save raw XML to cache, parse + return.
    404 → return None (pre-iXBRL filing). Other HTTPErrors propagate up.
    """
    cached_xml = load_filing_summary(sec_root, metadata.ticker, metadata.accession)
    if cached_xml is not None:
        return _parse_filing_summary(cached_xml)

    raw_xml = fetch_filing_summary_raw(metadata)
    if raw_xml is None:
        # Pre-iXBRL filing or genuinely missing manifest. Don't cache the
        # "not found" — cheap to retry on the next index run in case the
        # filing gets amended.
        return None

    save_filing_summary(sec_root, metadata.ticker, metadata.accession, raw_xml)
    return _parse_filing_summary(raw_xml)


# iXBRL framework metadata that SEC's R-file renderer interleaves with the
# actual statement figures. These lines carry no analytical value and pollute
# downstream search — qualitative queries (moat, management) end up ranking
# taxonomy boilerplate above narrative. Patterns derive from the canonical
# Zo's observation on IBM R-files (issue #43): element type descriptors,
# period-type labels, definition markers, and taxonomy URIs.
#
# CONSERVATIVE by design: the filter drops a line only when it clearly matches
# a metadata signature, and never touches a data row (label + numeric
# columns). Worst case it under-strips (some noise survives) — never
# over-strips real figures.
#
# NOTE (issue #43): pattern set is tuned against the Zo's described format and
# should be validated against real R-file text before relying on completeness.
# Add patterns here as new noise shapes surface; the structure makes that a
# one-line change.
_XBRL_NOISE_LINE_RE = re.compile(
    r"^\s*(?:"
    r"type:\s*(?:credit|debit)\b"                 # element balance type
    r"|period\s*type:\s*(?:duration|instant)\b"   # element period type
    r"|x\s*[-–—]\s*definition\b"                   # iXBRL "X — Definition" marker
    r"|no\s+definition\s+available\.?\s*$"         # placeholder definition row
    r"|definition\s*$"                             # bare "Definition" label line
    r"|https?://\S*(?:xbrl|fasb\.org|sec\.gov/CIK)\S*"  # taxonomy / namespace URIs
    r")",
    re.IGNORECASE,
)


def _strip_xbrl_metadata(text: str) -> str:
    """Drop iXBRL framework-metadata lines from rendered R-file text (issue #43).

    SEC's iXBRL renderer interleaves element definitions, balance/period-type
    descriptors, and taxonomy URIs with the statement figures. They survive
    ``html_to_text`` and degrade search precision. This conservative line
    filter removes only lines matching clear metadata signatures
    (``_XBRL_NOISE_LINE_RE``) and collapses the blank-line runs a removed
    block leaves behind. Data rows and any unrecognized line pass through
    untouched.
    """
    kept = [ln for ln in text.splitlines() if not _XBRL_NOISE_LINE_RE.match(ln)]
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept))
    return cleaned.strip()


def _assemble_recovered_text(
    metadata: FilingMetadata,
    statements: list,  # list[FilingSummaryReport]
    sec_root: Path,
) -> str:
    """Fetch + concatenate R-file text for every Statements report.

    Each R-file is fetched once (cache-first), extracted to text, then
    stripped of iXBRL framework noise (issue #43). Text is prefixed with a
    ``# ShortName`` heading so downstream readers can tell where one
    statement ends and the next begins.
    """
    pieces: list[str] = []
    for report in statements:
        html = _get_or_fetch_r_file(metadata, report.html_file_name, sec_root)
        if html is None:
            logger.warning(
                "Phase 2 recovery: R-file %s missing for %s %s",
                report.html_file_name, metadata.ticker, metadata.accession,
            )
            continue
        text = _strip_xbrl_metadata(html_to_text(html))
        if not text:
            continue
        pieces.append(f"# {report.short_name}\n\n{text}")
    return "\n\n".join(pieces)


def _get_or_fetch_r_file(
    metadata: FilingMetadata,
    name: str,
    sec_root: Path,
) -> str | None:
    """Return cached R-file HTML, fetching + caching on a cold miss."""
    cached = load_r_file(sec_root, metadata.ticker, metadata.accession, name)
    if cached is not None:
        return cached
    try:
        html = fetch_r_file(metadata, name)
    except Exception as e:  # noqa: BLE001 — network errors are heterogeneous
        logger.warning(
            "Phase 2 recovery: R-file fetch failed for %s %s %s: %s",
            metadata.ticker, metadata.accession, name, e,
        )
        return None
    save_r_file(sec_root, metadata.ticker, metadata.accession, name, html)
    return html
