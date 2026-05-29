"""Tests for ai_buffett_zo.observability.version (issue #55)."""

from __future__ import annotations

from pathlib import Path

from ai_buffett_zo import __version__
from ai_buffett_zo.observability import CodeVersion, code_version
from ai_buffett_zo.observability.version import _git_short_commit


def test_code_version_reports_package_version() -> None:
    assert code_version().version == __version__


def test_code_version_commit_is_str_or_none() -> None:
    commit = code_version().commit
    assert commit is None or isinstance(commit, str)


def test_label_includes_commit_when_present() -> None:
    assert CodeVersion("0.1.0", "abc1234").label() == "0.1.0+gabc1234"


def test_label_falls_back_to_version_without_commit() -> None:
    assert CodeVersion("0.1.0", None).label() == "0.1.0"


def test_git_short_commit_returns_none_outside_a_repo(tmp_path: Path) -> None:
    # tmp_path is not a git checkout → no commit, no crash.
    assert _git_short_commit(tmp_path) is None
