"""SEC EDGAR fetcher: ticker → CIK → submissions list → filing HTML.

Free public APIs (no key). SEC requires a User-Agent that identifies the caller;
we default to a generic Clarion Intelligence System UA but encourage users to
override via $SEC_USER_AGENT.

Tests monkeypatch the module-level `_get_json` and `_get_text` seams.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, timedelta

DEFAULT_USER_AGENT = "Clarion Intelligence System (clarion@example.com)"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{primary_doc}"
# FilingSummary.xml is the iXBRL-rendered manifest at the accession root that
# lists every report (statements, notes, cover pages, etc.). Recovery for
# pointer-only Items 7/8 (issue #26) reads this to find the R-file containing
# the actual Consolidated Income Statement / Balance Sheet / Cash Flows.
FILING_SUMMARY_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/FilingSummary.xml"


class FilingNotFound(Exception):
    """Ticker or form not found in SEC EDGAR."""


@dataclass(frozen=True)
class FilingMetadata:
    """Identifying info for one filing. Stable across re-indexing."""

    cik: str            # 10-digit zero-padded
    ticker: str
    company: str
    form: str           # "10-K", "10-Q", etc.
    filed: date         # date filed with SEC
    period: date        # period of report (fiscal end)
    accession: str      # with dashes, e.g. "0000320193-25-000123"
    primary_doc: str    # filename
    primary_doc_url: str


def fetch_filing(
    ticker: str,
    *,
    form: str = "10-K",
    user_agent: str | None = None,
) -> tuple[FilingMetadata, str]:
    """Fetch the latest `form` filing for `ticker`. Returns (metadata, raw_html).

    Raises FilingNotFound if the ticker is unknown or no `form` filing exists.
    """
    ua = user_agent or os.environ.get("SEC_USER_AGENT") or DEFAULT_USER_AGENT
    cik, company = _ticker_to_cik(ticker, user_agent=ua)
    submissions = _get_json(SUBMISSIONS_URL.format(cik=cik), user_agent=ua)
    entry = _find_latest(submissions, form)
    accession = entry["accession"]
    # Strip SEC's XSLT renderer prefix (e.g., `xslF345X06/`) before building the
    # fetch URL. EDGAR's submissions feed reports primaryDocument paths like
    # `xslF345X06/wk-form4_xxxx.xml` for forms with server-side renderers
    # (Forms 3/4/5). Fetching that URL returns the HTML-rendered version, not
    # the raw XML — which our XML parser can't read. The canonical raw XML
    # lives at the same path minus the `xsl.../` prefix.
    primary_doc = _strip_xslt_prefix(entry["primary_doc"])
    primary_doc_url = ARCHIVE_URL.format(
        cik_int=int(cik),
        accession_nodash=accession.replace("-", ""),
        primary_doc=primary_doc,
    )
    metadata = FilingMetadata(
        cik=cik,
        ticker=ticker.upper(),
        company=company,
        form=form,
        filed=date.fromisoformat(entry["filed"]),
        period=date.fromisoformat(entry["period"]),
        accession=accession,
        primary_doc=primary_doc,
        primary_doc_url=primary_doc_url,
    )
    html = _get_text(primary_doc_url, user_agent=ua)
    return metadata, html


def list_recent_filings(
    ticker: str,
    *,
    form: str | None = None,
    since_days: int | None = None,
    limit: int | None = None,
    asof: date | None = None,
    user_agent: str | None = None,
) -> list[FilingMetadata]:
    """List recent filings for ``ticker``, newest first.

    Lightweight — fetches the submissions feed once but does NOT download
    each filing's primary document. Callers wanting actual HTML body should
    pass the returned accession to ``fetch_filing_by_accession``.

    Filters compose:
      - ``form``: case- and whitespace-insensitive match (e.g. ``"DEF 14A"`` matches ``"DEF14A"``). None → all forms.
      - ``since_days``: only filings filed within the last N days from ``asof``. None → no date filter.
      - ``limit``: cap the result count. None → no cap.

    ``asof`` defaults to today; tests pass a fixed date for determinism.
    """
    ua = user_agent or os.environ.get("SEC_USER_AGENT") or DEFAULT_USER_AGENT
    cik, company = _ticker_to_cik(ticker, user_agent=ua)
    submissions = _get_json(SUBMISSIONS_URL.format(cik=cik), user_agent=ua)
    entries = _find_recent_filings(
        submissions, form=form, since_days=since_days, limit=limit, asof=asof
    )
    out: list[FilingMetadata] = []
    for entry in entries:
        accession = entry["accession"]
        primary_doc = _strip_xslt_prefix(entry["primary_doc"])
        primary_doc_url = ARCHIVE_URL.format(
            cik_int=int(cik),
            accession_nodash=accession.replace("-", ""),
            primary_doc=primary_doc,
        )
        out.append(
            FilingMetadata(
                cik=cik,
                ticker=ticker.upper(),
                company=company,
                form=entry["form"],
                filed=date.fromisoformat(entry["filed"]),
                period=date.fromisoformat(entry["period"]),
                accession=accession,
                primary_doc=primary_doc,
                primary_doc_url=primary_doc_url,
            )
        )
    return out


def fetch_filing_by_accession(
    ticker: str,
    accession: str,
    *,
    user_agent: str | None = None,
) -> tuple[FilingMetadata, str]:
    """Fetch a specific filing by accession number. Returns (metadata, raw_html).

    Used by the indexer service to fulfill ``IndexRequest`` objects that
    target a specific filing (the multi-filing indexing path). Raises
    ``FilingNotFound`` if the accession isn't in the ticker's submissions feed.
    """
    ua = user_agent or os.environ.get("SEC_USER_AGENT") or DEFAULT_USER_AGENT
    cik, company = _ticker_to_cik(ticker, user_agent=ua)
    submissions = _get_json(SUBMISSIONS_URL.format(cik=cik), user_agent=ua)
    entry = _find_by_accession(submissions, accession)
    primary_doc = _strip_xslt_prefix(entry["primary_doc"])
    primary_doc_url = ARCHIVE_URL.format(
        cik_int=int(cik),
        accession_nodash=accession.replace("-", ""),
        primary_doc=primary_doc,
    )
    metadata = FilingMetadata(
        cik=cik,
        ticker=ticker.upper(),
        company=company,
        form=entry["form"],
        filed=date.fromisoformat(entry["filed"]),
        period=date.fromisoformat(entry["period"]),
        accession=accession,
        primary_doc=primary_doc,
        primary_doc_url=primary_doc_url,
    )
    html = _get_text(primary_doc_url, user_agent=ua)
    return metadata, html


def _ticker_to_cik(ticker: str, *, user_agent: str) -> tuple[str, str]:
    """Resolve a ticker to (cik_padded, company_name) via SEC's tickers map."""
    data = _get_json(TICKERS_URL, user_agent=user_agent)
    ticker_upper = ticker.upper()
    for entry in data.values():
        if entry.get("ticker", "").upper() == ticker_upper:
            return f"{int(entry['cik_str']):010d}", entry.get("title", ticker_upper)
    raise FilingNotFound(f"ticker not in SEC tickers map: {ticker}")


_XSLT_PREFIX_RE = re.compile(r"^xsl[^/]+/")


def _strip_xslt_prefix(primary_doc: str) -> str:
    """Strip SEC EDGAR's XSLT-renderer path prefix from a primary-document name.

    Form 3/4/5 ownership filings are stored as XML but EDGAR's submissions feed
    points at an XSLT-rendered HTML version under `xslF345X06/` (or similar).
    The canonical raw XML is at the same path with that prefix removed.
    Example:
        xslF345X06/wk-form4_xxxx.xml  →  wk-form4_xxxx.xml
    """
    return _XSLT_PREFIX_RE.sub("", primary_doc)


def _normalize_form_match(form: str) -> str:
    """Normalize a form name for matching against EDGAR's submissions feed.

    EDGAR canonicalizes form names with embedded whitespace (`DEF 14A`,
    `PRE 14A`, `N-CSR`) and mixed case. Users (and chat agents reading
    SKILL.md examples) reasonably pass either `"DEF 14A"` or `"DEF14A"`,
    or even lowercase variants. Match should not care about either.

    Does NOT strip the `/A` amendment suffix — `10-K` and `10-K/A` are
    genuinely different filings in EDGAR and must stay distinguishable.
    """
    return form.replace(" ", "").upper()


def _find_latest(submissions: dict, form: str) -> dict:
    """Find the most-recent filing of `form` in a submissions response.

    The submissions JSON has parallel arrays under filings.recent. We scan in
    order (newest first per SEC convention) and return the first match.
    Form matching is whitespace-insensitive and case-insensitive — see
    `_normalize_form_match`.
    """
    try:
        recent = submissions["filings"]["recent"]
    except KeyError as e:
        raise FilingNotFound("submissions JSON missing filings.recent") from e

    target = _normalize_form_match(form)
    forms = recent.get("form", [])
    for i, f in enumerate(forms):
        if _normalize_form_match(f) == target:
            return {
                "accession": recent["accessionNumber"][i],
                "filed": recent["filingDate"][i],
                "period": recent["reportDate"][i] or recent["filingDate"][i],
                "primary_doc": recent["primaryDocument"][i],
            }
    raise FilingNotFound(f"no {form} in recent submissions")


def _find_recent_filings(
    submissions: dict,
    *,
    form: str | None,
    since_days: int | None,
    limit: int | None,
    asof: date | None,
) -> list[dict]:
    """Return all submission entries matching the filters, newest first.

    Filters compose as AND. ``form=None`` skips the form check. ``since_days=None``
    skips the date check. ``limit=None`` returns everything.
    """
    try:
        recent = submissions["filings"]["recent"]
    except KeyError as e:
        raise FilingNotFound("submissions JSON missing filings.recent") from e

    target = _normalize_form_match(form) if form is not None else None
    cutoff: date | None = None
    if since_days is not None:
        cutoff = (asof or date.today()) - timedelta(days=since_days)

    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    filed_dates = recent.get("filingDate", [])
    period_dates = recent.get("reportDate", [])
    primary_docs = recent.get("primaryDocument", [])

    out: list[dict] = []
    for i, f in enumerate(forms):
        if target is not None and _normalize_form_match(f) != target:
            continue
        try:
            filed = date.fromisoformat(filed_dates[i])
        except (IndexError, ValueError):
            continue
        if cutoff is not None and filed < cutoff:
            continue
        out.append(
            {
                "accession": accessions[i],
                "form": f,
                "filed": filed_dates[i],
                "period": period_dates[i] or filed_dates[i],
                "primary_doc": primary_docs[i],
            }
        )
    # EDGAR's submissions feed is *approximately* newest-first but not strictly
    # guaranteed (especially across multiple form types). Sort explicitly so
    # callers can rely on the order — and so the `limit` cap applies to the
    # genuinely-most-recent N, not the first N in feed order.
    out.sort(key=lambda e: e["filed"], reverse=True)
    if limit is not None:
        out = out[:limit]
    return out


def _find_by_accession(submissions: dict, accession: str) -> dict:
    """Locate a single submission entry by accession number."""
    try:
        recent = submissions["filings"]["recent"]
    except KeyError as e:
        raise FilingNotFound("submissions JSON missing filings.recent") from e

    accessions = recent.get("accessionNumber", [])
    for i, a in enumerate(accessions):
        if a == accession:
            return {
                "accession": a,
                "form": recent.get("form", [""])[i],
                "filed": recent.get("filingDate", [""])[i],
                "period": (
                    recent.get("reportDate", [""])[i]
                    or recent.get("filingDate", [""])[i]
                ),
                "primary_doc": recent.get("primaryDocument", [""])[i],
            }
    raise FilingNotFound(f"accession {accession} not in recent submissions")


# --- FilingSummary.xml + R-file recovery (issue #26 Phase 2) ----------------
#
# Modern SEC filings (post-iXBRL adoption, ~2012+) ship a `FilingSummary.xml`
# manifest at the accession root that catalogs every rendered report:
#
#   <Report instance="ibm-20251231.htm">
#     <IsDefault>false</IsDefault>
#     <MenuCategory>Statements</MenuCategory>
#     <ShortName>CONSOLIDATED INCOME STATEMENT</ShortName>
#     <LongName>1003003 - Statement - CONSOLIDATED INCOME STATEMENT</LongName>
#     <HtmlFileName>R3.htm</HtmlFileName>
#     <Position>3</Position>
#   </Report>
#
# Each `R{n}.htm` is a single SEC-rendered HTML table — the actual statement.
# This is the canonical anchor for recovering substantive content when an
# Item 7 / Item 8 section is just a pointer (e.g. "see the Annual Report" or
# "Refer to..."). Verified structure on IBM, KO, PG, NVDA — every modern
# 10-K has it.


@dataclass(frozen=True)
class FilingSummaryReport:
    """One <Report> entry in a filing's FilingSummary.xml manifest."""

    short_name: str         # e.g. "CONSOLIDATED INCOME STATEMENT"
    long_name: str          # e.g. "1003003 - Statement - CONSOLIDATED INCOME STATEMENT"
    html_file_name: str     # e.g. "R3.htm" — relative to the accession dir
    menu_category: str      # "Statements" | "Notes" | "Cover" | "Tables" | ""
    position: int           # ordering in the filing


@dataclass(frozen=True)
class FilingSummary:
    """Parsed FilingSummary.xml for one accession."""

    reports: list[FilingSummaryReport]

    def statements(self) -> list[FilingSummaryReport]:
        """Reports the manifest marks as financial statements.

        These are the primary recovery targets for pointer-only Items 7/8.
        Notes (MenuCategory == "Notes") are deliberately excluded here so
        callers can opt in separately — they bulk up the recovered content
        considerably (often 30+ reports vs ~7 for statements).
        """
        return [r for r in self.reports if r.menu_category == "Statements"]


def fetch_filing_summary_raw(
    metadata: FilingMetadata,
    *,
    user_agent: str | None = None,
) -> str | None:
    """Fetch the raw FilingSummary.xml bytes for an accession.

    Returns the XML string, or None when the manifest doesn't exist (404)
    — typical for pre-iXBRL filings (~pre-2012). Other HTTPErrors / URLError
    propagate up so callers can log them.

    Lives at the same layer as ``_get_text`` so the recovery cache layer
    can persist raw XML and parse on read — keeps the cache format simple.
    """
    ua = user_agent or os.environ.get("SEC_USER_AGENT") or DEFAULT_USER_AGENT
    url = FILING_SUMMARY_URL.format(
        cik_int=int(metadata.cik),
        accession_nodash=metadata.accession.replace("-", ""),
    )
    try:
        return _get_text(url, user_agent=ua)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def fetch_filing_summary(
    metadata: FilingMetadata,
    *,
    user_agent: str | None = None,
) -> FilingSummary | None:
    """Fetch and parse FilingSummary.xml for an accession.

    Thin wrapper over ``fetch_filing_summary_raw`` + ``_parse_filing_summary``.
    Use ``fetch_filing_summary_raw`` directly when the caller needs the
    raw bytes for caching.
    """
    raw = fetch_filing_summary_raw(metadata, user_agent=user_agent)
    if raw is None:
        return None
    return _parse_filing_summary(raw)


def fetch_r_file(
    metadata: FilingMetadata,
    html_file_name: str,
    *,
    user_agent: str | None = None,
) -> str:
    """Fetch one rendered statement file (e.g. R3.htm) from an accession.

    Returns the raw HTML string. Caller is responsible for extracting text
    via `secrag.sections.html_to_text` and concatenating multiple R-files.
    """
    ua = user_agent or os.environ.get("SEC_USER_AGENT") or DEFAULT_USER_AGENT
    url = ARCHIVE_URL.format(
        cik_int=int(metadata.cik),
        accession_nodash=metadata.accession.replace("-", ""),
        primary_doc=html_file_name,
    )
    return _get_text(url, user_agent=ua)


def _parse_filing_summary(xml: str) -> FilingSummary:
    """Parse FilingSummary.xml into a typed `FilingSummary`.

    SEC's manifest format is stable across filers but resilient to missing
    optional fields — `MenuCategory` is occasionally absent for utility
    reports (e.g. cover pages on some legacy filings). We tolerate that.
    """
    root = ET.fromstring(xml)
    reports: list[FilingSummaryReport] = []
    for report_elem in root.iter("Report"):
        reports.append(
            FilingSummaryReport(
                short_name=_xml_text(report_elem, "ShortName"),
                long_name=_xml_text(report_elem, "LongName"),
                html_file_name=_xml_text(report_elem, "HtmlFileName"),
                menu_category=_xml_text(report_elem, "MenuCategory"),
                position=_xml_int(report_elem, "Position"),
            )
        )
    return FilingSummary(reports=reports)


def _xml_text(elem: ET.Element, tag: str) -> str:
    sub = elem.find(tag)
    if sub is None or sub.text is None:
        return ""
    return sub.text.strip()


def _xml_int(elem: ET.Element, tag: str) -> int:
    raw = _xml_text(elem, tag)
    try:
        return int(raw)
    except ValueError:
        return 0


# --- HTTP seams (monkeypatched in tests) ------------------------------------


def _get_json(url: str, *, user_agent: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_text(url: str, *, user_agent: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")
