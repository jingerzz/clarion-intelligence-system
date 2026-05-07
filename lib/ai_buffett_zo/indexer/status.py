"""Per-ticker indexing status.

Written to {sec_root}/{TICKER}/.status.json. Skill scripts read this to
answer "is NVDA indexed yet?" and "what was the last request's outcome?"
without scanning the on-disk filings.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

RequestState = Literal["pending", "running", "completed", "failed"]
FilingState = Literal["indexed", "raw_only"]


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
