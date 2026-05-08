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
import urllib.request
from dataclasses import dataclass
from datetime import date

DEFAULT_USER_AGENT = "Clarion Intelligence System (clarion@example.com)"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{primary_doc}"


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


# --- HTTP seams (monkeypatched in tests) ------------------------------------


def _get_json(url: str, *, user_agent: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_text(url: str, *, user_agent: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")
