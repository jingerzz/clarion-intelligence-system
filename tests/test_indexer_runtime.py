"""Tests for ai_buffett_zo.indexer.runtime (issue #55)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_buffett_zo.indexer import indexer_health, write_runtime_marker
from ai_buffett_zo.indexer import runtime as runtime_mod
from ai_buffett_zo.observability import CodeVersion


def test_health_no_marker(tmp_path: Path) -> None:
    h = indexer_health(tmp_path)
    assert h.running is False
    assert h.stale is False
    assert "no runtime marker" in h.message()


def test_marker_contents(tmp_path: Path) -> None:
    write_runtime_marker(tmp_path, CodeVersion("0.1.0", "abc1234"))
    d = json.loads((tmp_path / runtime_mod.RUNTIME_MARKER).read_text())
    assert d["version"] == "0.1.0"
    assert d["commit"] == "abc1234"
    assert "pid" in d
    assert "started_at" in d


def test_health_fresh_when_running_matches_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtime_mod, "code_version", lambda: CodeVersion("0.1.0", "abc1234"))
    write_runtime_marker(tmp_path, CodeVersion("0.1.0", "abc1234"))
    h = indexer_health(tmp_path)
    assert h.running is True
    assert h.stale is False
    assert h.running_commit == "abc1234"
    assert "up to date" in h.message()


def test_health_stale_when_running_differs_from_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_runtime_marker(tmp_path, CodeVersion("0.1.0", "oldcafe"))      # running
    monkeypatch.setattr(runtime_mod, "code_version", lambda: CodeVersion("0.1.0", "newbeef"))  # installed
    h = indexer_health(tmp_path)
    assert h.stale is True
    assert h.running_commit == "oldcafe"
    assert h.installed_commit == "newbeef"
    assert "STALE" in h.message()


def test_health_not_stale_when_commit_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No git → commit None on both sides → can't prove staleness, don't cry wolf.
    write_runtime_marker(tmp_path, CodeVersion("0.1.0", None))
    monkeypatch.setattr(runtime_mod, "code_version", lambda: CodeVersion("0.1.0", None))
    h = indexer_health(tmp_path)
    assert h.running is True
    assert h.stale is False


def test_health_handles_corrupt_marker(tmp_path: Path) -> None:
    (tmp_path / runtime_mod.RUNTIME_MARKER).write_text("not json")
    h = indexer_health(tmp_path)
    assert h.running is False  # treated as missing rather than crashing
