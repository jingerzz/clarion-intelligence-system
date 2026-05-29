"""Runtime marker + staleness check for the sec-indexer service (issue #55).

The indexer is a long-running process; an editable reinstall does not reload
it. To make "the service is running stale code" detectable instead of silent,
the indexer writes a marker at startup recording the code it actually loaded
(``write_runtime_marker``), and ``indexer_health`` compares that against the
code currently installed on disk. ``clarion-sec-research doctor`` surfaces it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ai_buffett_zo.observability.version import CodeVersion, code_version

RUNTIME_MARKER = ".indexer_runtime.json"


def write_runtime_marker(sec_root: Path, version: CodeVersion) -> None:
    """Record what code the running indexer process is executing.

    Overwritten on every service start, so the marker always reflects the
    currently-running process — not a historical one.
    """
    sec_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": version.version,
        "commit": version.commit,
        "pid": os.getpid(),
        "started_at": datetime.now(UTC).isoformat(),
    }
    (sec_root / RUNTIME_MARKER).write_text(json.dumps(payload, indent=2))


@dataclass(frozen=True)
class IndexerHealth:
    """Whether the running indexer matches the installed code (issue #55)."""

    running: bool                  # a runtime marker exists
    running_commit: str | None     # commit the running process loaded
    installed_commit: str | None   # commit on disk now
    started_at: str | None
    stale: bool                    # running != installed (both known)

    def message(self) -> str:
        if not self.running:
            return (
                "Indexer: no runtime marker — the sec-indexer service may not have "
                "started since this version. Start/restart it before indexing."
            )
        if self.stale:
            return (
                f"Indexer: STALE — running commit {self.running_commit} but installed "
                f"code is {self.installed_commit}. Restart the sec-indexer service so "
                "indexing uses the current code (issue #55)."
            )
        running = self.running_commit or "unknown"
        return f"Indexer: up to date (commit {running}, started {self.started_at})."


def is_tree_stale(existing_commit: str | None, current_commit: str | None) -> bool:
    """Should a tree built at ``existing_commit`` be re-extracted now? (issue #57)

    True when the running code (``current_commit``) differs from the code that
    built the tree — including the legacy case where the tree predates commit
    stamping (``existing_commit`` is None). When the running commit is unknown
    (no git), we can't tell, so we don't auto-re-extract — ``--force`` still works.
    """
    if current_commit is None:
        return False
    return existing_commit != current_commit


def indexer_health(sec_root: Path) -> IndexerHealth:
    """Compare the running indexer's code against what's installed on disk.

    ``stale`` is only asserted when both commits are known and differ — when
    git isn't available (commit is None) we can't prove staleness, so we don't
    cry wolf.
    """
    installed = code_version().commit
    marker = sec_root / RUNTIME_MARKER
    if not marker.exists():
        return IndexerHealth(False, None, installed, None, False)
    try:
        d = json.loads(marker.read_text())
    except (OSError, json.JSONDecodeError):
        return IndexerHealth(False, None, installed, None, False)
    running = d.get("commit")
    stale = bool(running and installed and running != installed)
    return IndexerHealth(True, running, installed, d.get("started_at"), stale)
