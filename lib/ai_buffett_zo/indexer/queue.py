"""File-based queue for sec-indexer.

Layout under {queue_root} (default ~/clarion/queue/):

    {id}.json              pending requests
    .processing/{id}.json  currently being processed
    .done/{id}.json        successfully completed (kept for audit)
    .failed/{id}.json      failed; error appended to body

Atomicity: we move files between dirs (rename is atomic on POSIX). No locks —
single producer (a skill script writing JSON) and single consumer (the
indexer service) is the assumed contract.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from ai_buffett_zo._paths import clarion_home

DEFAULT_QUEUE_ROOT = clarion_home() / "queue"


@dataclass
class IndexRequest:
    """One indexing request submitted via the queue.

    `model` is optional — if None, the indexer uses its default.
    `id` is a stable identifier producers can use to poll status.
    """

    id: str
    ticker: str
    form: str
    requested_at: str               # ISO-8601 UTC
    model: str | None = None

    @classmethod
    def new(
        cls,
        ticker: str,
        form: str = "10-K",
        *,
        model: str | None = None,
    ) -> IndexRequest:
        return cls(
            id=uuid.uuid4().hex[:12],
            ticker=ticker.upper(),
            form=form,
            requested_at=datetime.now(UTC).isoformat(),
            model=model,
        )


def enqueue(request: IndexRequest, *, root: Path = DEFAULT_QUEUE_ROOT) -> Path:
    """Write a pending request file to the queue. Returns the file path."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{request.id}.json"
    path.write_text(json.dumps(asdict(request), indent=2))
    return path


def list_pending(root: Path = DEFAULT_QUEUE_ROOT) -> list[IndexRequest]:
    """Return pending requests in submission order (oldest first)."""
    if not root.exists():
        return []
    files = sorted(
        (
            p
            for p in root.iterdir()
            if p.is_file() and p.suffix == ".json" and not p.name.startswith(".")
        ),
        key=lambda p: p.stat().st_mtime,
    )
    out: list[IndexRequest] = []
    for f in files:
        try:
            d = json.loads(f.read_text())
            out.append(IndexRequest(**d))
        except (json.JSONDecodeError, TypeError):
            continue
    return out


def claim(request_id: str, *, root: Path = DEFAULT_QUEUE_ROOT) -> Path | None:
    """Atomically move pending → .processing/. Returns new path, or None if missing."""
    src = root / f"{request_id}.json"
    if not src.exists():
        return None
    dest_dir = root / ".processing"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    src.rename(dest)
    return dest


def mark_done(request_id: str, *, root: Path = DEFAULT_QUEUE_ROOT) -> None:
    """Move .processing/{id}.json to .done/. Idempotent on missing source."""
    src = root / ".processing" / f"{request_id}.json"
    if not src.exists():
        return
    dest_dir = root / ".done"
    dest_dir.mkdir(parents=True, exist_ok=True)
    src.rename(dest_dir / src.name)


def mark_failed(
    request_id: str,
    error: str,
    *,
    root: Path = DEFAULT_QUEUE_ROOT,
) -> None:
    """Move .processing/{id}.json to .failed/, appending error info to body."""
    src = root / ".processing" / f"{request_id}.json"
    if not src.exists():
        return
    dest_dir = root / ".failed"
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        d = json.loads(src.read_text())
    except json.JSONDecodeError:
        d = {}
    d["error"] = error
    d["failed_at"] = datetime.now(UTC).isoformat()
    dest = dest_dir / src.name
    dest.write_text(json.dumps(d, indent=2))
    src.unlink()
