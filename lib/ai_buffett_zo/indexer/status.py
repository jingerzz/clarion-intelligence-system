"""Per-ticker indexing status.

Written to {sec_root}/{TICKER}/.status.json. Skill scripts read this to
answer "is NVDA indexed yet?" and "what was the last request's outcome?"
without scanning the on-disk filings.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

RequestState = Literal["pending", "running", "completed", "failed"]
FilingState = Literal["indexed", "raw_only"]

# High-signal coverage tiers for eval-readiness (issue #38). A Buffett
# first-pass eval needs the latest annual report; quarterly + proxy enrich it
# but don't gate it. Eval-ready == the core annual report is indexed, so the
# user can evaluate the moment that one filing lands instead of waiting for the
# whole queue (8-Ks, Form 4s, etc.) to drain.
CORE_FORMS = frozenset({"10-K", "20-F", "40-F"})  # annual report (US / foreign)
QUARTERLY_FORMS = frozenset({"10-Q"})
PROXY_FORMS = frozenset({"DEF 14A", "DEFA14A", "DEF 14C"})

# Core-form preference order — which annual report to name when several exist.
_CORE_PREFERENCE = ("10-K", "20-F", "40-F")


@dataclass
class FilingStatus:
    """Per-filing entry inside a TickerStatus."""

    accession: str
    form: str
    filed: str               # ISO date
    indexed_at: str          # ISO datetime UTC
    status: FilingState


@dataclass
class TickerStatus:
    """All known indexing state for one ticker."""

    ticker: str
    filings: list[FilingStatus] = field(default_factory=list)
    last_request: dict[str, Any] | None = None

    def merge_filing(self, f: FilingStatus) -> None:
        """Replace existing entry with same accession, or append if new."""
        for i, existing in enumerate(self.filings):
            if existing.accession == f.accession:
                self.filings[i] = f
                return
        self.filings.append(f)

    def update_request(
        self,
        *,
        form: str,
        state: RequestState,
        error: str | None = None,
    ) -> None:
        self.last_request = {
            "form": form,
            "state": state,
            "updated_at": datetime.now(UTC).isoformat(),
            "error": error,
        }


def status_path(sec_root: Path, ticker: str) -> Path:
    return sec_root / ticker.upper() / ".status.json"


def load_status(sec_root: Path, ticker: str) -> TickerStatus:
    """Return current status for ticker, or empty if no status file yet."""
    path = status_path(sec_root, ticker)
    if not path.exists():
        return TickerStatus(ticker=ticker.upper())
    data = json.loads(path.read_text())
    return TickerStatus(
        ticker=data["ticker"],
        filings=[FilingStatus(**f) for f in data.get("filings", [])],
        last_request=data.get("last_request"),
    )


def save_status(sec_root: Path, status: TickerStatus) -> None:
    path = status_path(sec_root, status.ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ticker": status.ticker,
        "filings": [asdict(f) for f in status.filings],
        "last_request": status.last_request,
    }
    path.write_text(json.dumps(payload, indent=2))


# ---- eval-readiness (issue #38) --------------------------------------------


def _base_form(form: str) -> str:
    """Strip amendment suffix so a 10-K/A still counts as a 10-K."""
    f = (form or "").strip().upper()
    if f.endswith("/A"):
        f = f[:-2].rstrip()
    return f


@dataclass
class Coverage:
    """High-signal filing coverage for a ticker (issue #38).

    ``eval_ready`` is True once the core annual report (10-K / 20-F / 40-F) is
    indexed — the minimum a Buffett first-pass eval needs. ``has_quarterly``
    and ``has_proxy`` enrich the eval (recent results, governance) but do not
    gate it: a user can evaluate the moment the annual report lands.
    """

    ticker: str
    eval_ready: bool
    has_core: bool
    has_quarterly: bool
    has_proxy: bool
    core_form: str | None        # which annual-report form is indexed
    indexed_count: int           # number of indexed filings considered

    def missing(self) -> list[str]:
        """Human-readable list of high-signal gaps (empty == fully covered)."""
        gaps: list[str] = []
        if not self.has_core:
            gaps.append("annual report (10-K / 20-F)")
        if not self.has_quarterly:
            gaps.append("latest quarterly (10-Q)")
        if not self.has_proxy:
            gaps.append("proxy (DEF 14A)")
        return gaps


def assess_coverage(ticker: str, forms: Iterable[str]) -> Coverage:
    """Assess eval-readiness from the set of indexed forms (issue #38).

    Takes the forms of a ticker's indexed filings (callers pass
    ``[f.form for f in ...]`` from either ``FilingStatus`` or
    ``FilingMetadata``). Amendment suffixes are normalized, so a 10-K/A
    satisfies core coverage.
    """
    normalized = [_base_form(f) for f in forms]
    present = set(normalized)
    core_form = next((f for f in _CORE_PREFERENCE if f in present), None)
    return Coverage(
        ticker=ticker.upper(),
        eval_ready=core_form is not None,
        has_core=core_form is not None,
        has_quarterly=bool(present & QUARTERLY_FORMS),
        has_proxy=bool(present & PROXY_FORMS),
        core_form=core_form,
        indexed_count=len(normalized),
    )
