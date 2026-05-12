"""Central resolver for the Clarion data root directory.

Why this exists
---------------
Several modules need a default path under the user's Clarion workspace.
Previously each module hardcoded ``Path.home() / "clarion"``. That works on
a normal user account where $HOME *is* the user-visible workspace, but
breaks on Zo Computer, where skills run as root (home = /root) while the
file browser surfaces /home/workspace — making Clarion's theses, letters,
SEC filings, etc., invisible to the user.

Resolution order
----------------
1. ``CLARION_DATA_ROOT`` environment variable. Stripped and ``~``-expanded.
   Honoured first so users / service-registration can pin an exact path.
2. ``/home/workspace/clarion`` if ``/home/workspace`` exists. This is the
   Zo signal — the bootstrap clones the source repo into /home/workspace,
   so its presence reliably identifies a Zo workspace.
3. ``Path.home() / "clarion"`` — the original fallback for normal users.

Importantly: the value is captured at module-import time by every consumer
that builds a ``DEFAULT_*`` constant. For long-running processes (e.g. the
sec-indexer service), ``CLARION_DATA_ROOT`` must be set BEFORE the process
starts — setting it in a shell after import has no effect.

Usage
-----
::

    from ai_buffett_zo._paths import clarion_home

    DEFAULT_FOO_ROOT = clarion_home() / "foo"
"""

from __future__ import annotations

import os
from pathlib import Path

ZO_WORKSPACE = Path("/home/workspace")


def clarion_home() -> Path:
    """Return the Clarion data root. See module docstring for resolution order."""
    env = os.environ.get("CLARION_DATA_ROOT", "").strip()
    if env:
        return Path(env).expanduser()
    if ZO_WORKSPACE.is_dir():
        return ZO_WORKSPACE / "clarion"
    return Path.home() / "clarion"
