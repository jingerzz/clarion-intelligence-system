"""Lightweight observability helpers for Clarion workflows.

Currently exposes ``Timing`` — a small stage-timer for identifying latency
bottlenecks in long-running commands (single-stock eval, SEC indexer). See
issue #42 for the motivation: measure where the time goes before investing
in indexing profiles, queue priority, caching, or persona fast paths.
"""

from __future__ import annotations

from ai_buffett_zo.observability.timing import Timing

__all__ = ["Timing"]
