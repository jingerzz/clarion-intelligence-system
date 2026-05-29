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


# Scheduling priority tiers (issue #39). Lower number = processed first, so a
# 10-K never sits behind a queue of low-signal 13G/424B filings. Within a tier,
# the queue stays oldest-first (FIFO). Tiers, by decision value for a Buffett
# first-pass eval:
#   P1 — core financials (10-K, 10-Q, 20-F, 40-F): the filings that change the
#        answer; also what makes a ticker eval-ready (issue #38).
#   P2 — governance / events (DEF 14A, 8-K).
#   P3 — insider activity (Form 3/4/5).
#   P4 — low-signal / administrative (13D/G, S-8, 144, 424B, EFFECT, ARS, and
#        anything unrecognized) — useful for full diligence, never urgent.
PRIORITY_P1 = 1
PRIORITY_P2 = 2
PRIORITY_P3 = 3
PRIORITY_P4 = 4

# Fallback for unrecognized forms — sort last, never block eval-ready filings.
DEFAULT_PRIORITY = PRIORITY_P4

_PRIORITY_BY_FORM: dict[str, int] = {
    "10-K": PRIORITY_P1, "10-Q": PRIORITY_P1, "20-F": PRIORITY_P1, "40-F": PRIORITY_P1,
    "DEF 14A": PRIORITY_P2, "DEFA14A": PRIORITY_P2, "DEF 14C": PRIORITY_P2, "8-K": PRIORITY_P2,
    "3": PRIORITY_P3, "4": PRIORITY_P3, "5": PRIORITY_P3,
}


def _norm_form(form: str) -> str:
    """Normalize a form for priority lookup: upper, strip 'Form ' + '/A'.

    Kept local to queue.py to avoid a layering dependency on secrag.sections
    (queue is a lower-level module). Mirrors sections.normalize_form's intent.
    """
    f = (form or "").strip().upper()
    if f.endswith("/A"):
        f = f[:-2].rstrip()
    if f.startswith("FORM "):
        f = f[5:].lstrip()
    return f


def default_priority(form: str) -> int:
    """Scheduling priority for a SEC form (lower = processed sooner)."""
    return _PRIORITY_BY_FORM.get(_norm_form(form), DEFAULT_PRIORITY)


@dataclass
class IndexRequest:
    """One indexing request submitted via the queue.

    ``model`` is optional — if None, the indexer uses its default.
    ``id`` is a stable identifier producers can use to poll status.
    ``accession`` is optional and targets a specific filing. When None, the
    indexer fetches the latest filing of ``form`` (legacy single-result
    behavior). When set, the indexer fetches that specific filing.
    ``priority`` orders the queue (issue #39) — lower is processed first;
    derived from ``form`` by ``new()`` via ``default_priority``.
    """

    id: str
    ticker: str
    form: str
    requested_at: str               # ISO-8601 UTC
    model: str | None = None
    accession: str | None = None
    priority: int = DEFAULT_PRIORITY
    force: bool = False             # re-extract even if already indexed (issue #57)

    @classmethod
    def new(
        cls,
        ticker: str,
        form: str = "10-K",
        *,
        model: str | None = None,
        accession: str | None = None,
        priority: int | None = None,
        force: bool = False,
    ) -> IndexRequest:
        return cls(
            id=uuid.uuid4().hex[:12],
            ticker=ticker.upper(),
            form=form,
            requested_at=datetime.now(UTC).isoformat(),
            model=model,
            accession=accession,
            priority=priority if priority is not None else default_priority(form),
            force=force,
        )


def enqueue(request: IndexRequest, *, root: Path = DEFAULT_QUEUE_ROOT) -> Path:
    """Write a pending request file to the queue. Returns the file path."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{request.id}.json"
    path.write_text(json.dumps(asdict(request), indent=2))
    return path


def list_pending(root: Path = DEFAULT_QUEUE_ROOT) -> list[IndexRequest]:
    """Return pending requests in scheduling order (issue #39).

    Sorted by ``(priority, mtime)`` — highest-priority tier first (lowest
    number), and oldest-first (FIFO) within a tier. So a freshly enqueued
    10-K (P1) jumps ahead of a backlog of low-signal P4 filings, but two
    10-Ks still drain in submission order.

    Backward-compat: queue files written before #39 lack a ``priority`` key;
    we derive it from their ``form`` so they slot into the right tier rather
    than all defaulting to last.
    """
    if not root.exists():
        return []
    entries: list[tuple[int, float, IndexRequest]] = []
    for p in root.iterdir():
        if not (p.is_file() and p.suffix == ".json" and not p.name.startswith(".")):
            continue
        try:
            d = json.loads(p.read_text())
            if "priority" not in d:
                d["priority"] = default_priority(d.get("form", ""))
            req = IndexRequest(**d)
        except (json.JSONDecodeError, TypeError):
            continue
        entries.append((req.priority, p.stat().st_mtime, req))
    entries.sort(key=lambda e: (e[0], e[1]))
    return [req for _, _, req in entries]


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
