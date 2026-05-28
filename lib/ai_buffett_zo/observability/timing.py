"""Stage timer for Clarion workflows (issue #42).

A ``Timing`` accumulates named stage durations so long-running commands can
emit a compact "where did the time go" summary:

    Timing:
    - yfinance snapshot: 1.2s
    - regime check: 0.8s
    - SEC status: 0.1s
    - Buffett lens search: 2.4s
    Total: 4.5s

Two ways to record a stage:

- ``with t.stage("name"): ...`` — times the block, always records even if the
  block raises (so a failure still shows up in the summary).
- ``t.record("name", seconds)`` — for durations measured elsewhere (e.g. a
  subprocess that reports its own wall time).

The class is deliberately dependency-free and side-effect-free: it never
prints on its own. Callers decide whether/where to surface ``summary()``
(stderr for CLIs, the service log for the indexer). That keeps timing opt-in
and out of the way of structured stdout that other tools parse.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class Timing:
    """Accumulates named stage durations for one workflow run.

    ``stages`` preserves insertion order — the summary reads top-to-bottom in
    the order stages actually ran, which is what a human debugging latency
    wants to see.
    """

    stages: list[tuple[str, float]] = field(default_factory=list)
    # perf_counter is monotonic — immune to wall-clock adjustments mid-run.
    _start: float = field(default_factory=time.perf_counter)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Time a block of work, recording its duration under ``name``.

        Records even when the block raises, so a failing stage still appears
        in the summary (with the time spent before it blew up).
        """
        start = time.perf_counter()
        try:
            yield
        finally:
            self.stages.append((name, time.perf_counter() - start))

    def record(self, name: str, seconds: float) -> None:
        """Record a stage duration measured outside this timer."""
        self.stages.append((name, seconds))

    def total(self) -> float:
        """Wall time since this Timing was constructed."""
        return time.perf_counter() - self._start

    def summary(self, *, title: str = "Timing") -> str:
        """Render the compact multi-line summary.

        Always ends with a ``Total`` line measured from construction — which
        can exceed the sum of recorded stages (uninstrumented gaps) or fall
        short of it (overlapping/externally-recorded stages). The gap itself
        is a useful signal when debugging.
        """
        lines = [f"{title}:"]
        for name, secs in self.stages:
            lines.append(f"- {name}: {secs:.1f}s")
        lines.append(f"Total: {self.total():.1f}s")
        return "\n".join(lines)

    def as_dict(self) -> dict[str, float]:
        """Stage durations as a dict (last write wins on duplicate names).

        Handy for tests and for structured logging where a human-readable
        summary isn't wanted.
        """
        return dict(self.stages)
