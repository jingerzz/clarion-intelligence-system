"""Running-code identity: package version + git commit (issue #55).

A long-running service (the sec-indexer) keeps the Python it imported at
startup in memory. After a ``git pull`` + editable reinstall, the files on
disk change but the running process does not — so a re-index can silently use
stale code. This module gives that running code an identity (version + short
git commit) that the indexer stamps at startup, so staleness becomes
detectable instead of silent.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ai_buffett_zo import __version__


@dataclass(frozen=True)
class CodeVersion:
    """Identity of a running checkout. ``commit`` is None when unavailable."""

    version: str
    commit: str | None  # short git hash

    def label(self) -> str:
        return f"{self.version}+g{self.commit}" if self.commit else self.version


def _git_short_commit(repo_hint: Path) -> str | None:
    """Short HEAD commit of the repo containing ``repo_hint``, or None.

    Best-effort: returns None when git is absent, the path isn't a checkout
    (e.g. a packaged wheel install), or the call errors/times out. Callers must
    treat ``commit`` as optional.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_hint), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    commit = out.stdout.strip()
    return commit or None


def code_version() -> CodeVersion:
    """Best-effort identity of the currently-imported ai_buffett_zo code.

    Commit is resolved from the package's own location — an editable install
    (the Zo deployment) lives inside its git checkout, so this reflects the
    code actually loaded, not whatever happens to be cwd.
    """
    return CodeVersion(version=__version__, commit=_git_short_commit(Path(__file__).resolve().parent))
