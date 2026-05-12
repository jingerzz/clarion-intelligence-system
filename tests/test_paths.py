"""Tests for lib/ai_buffett_zo/_paths.py — the Clarion data-root resolver."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_buffett_zo import _paths
from ai_buffett_zo._paths import clarion_home


def test_env_var_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """CLARION_DATA_ROOT must override both Zo auto-detect and $HOME fallback."""
    monkeypatch.setenv("CLARION_DATA_ROOT", str(tmp_path / "custom"))
    monkeypatch.setattr(_paths, "ZO_WORKSPACE", tmp_path / "workspace-exists")
    (tmp_path / "workspace-exists").mkdir()
    assert clarion_home() == tmp_path / "custom"


def test_env_var_stripped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Trailing whitespace in the env var must not leak into the path."""
    monkeypatch.setenv("CLARION_DATA_ROOT", f"  {tmp_path / 'custom'}  ")
    assert clarion_home() == tmp_path / "custom"


def test_env_var_expands_tilde(monkeypatch: pytest.MonkeyPatch) -> None:
    """A literal ~ in the env var must expand. Common copy/paste footgun."""
    monkeypatch.setenv("CLARION_DATA_ROOT", "~/clarion-test")
    assert clarion_home() == Path.home() / "clarion-test"


def test_zo_autodetect(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When the Zo workspace dir exists and no env var, return its clarion/ child."""
    monkeypatch.delenv("CLARION_DATA_ROOT", raising=False)
    fake_zo = tmp_path / "zo-workspace"
    fake_zo.mkdir()
    monkeypatch.setattr(_paths, "ZO_WORKSPACE", fake_zo)
    assert clarion_home() == fake_zo / "clarion"


def test_home_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No env var and no Zo workspace dir → original $HOME/clarion behavior."""
    monkeypatch.delenv("CLARION_DATA_ROOT", raising=False)
    monkeypatch.setattr(_paths, "ZO_WORKSPACE", tmp_path / "does-not-exist")
    assert clarion_home() == Path.home() / "clarion"


def test_empty_env_var_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An empty/whitespace-only env var must not short-circuit to Path('').

    Guards against a misconfigured service registration that sets the var
    to an empty string clobbering the auto-detect.
    """
    monkeypatch.setenv("CLARION_DATA_ROOT", "   ")
    monkeypatch.setattr(_paths, "ZO_WORKSPACE", tmp_path / "does-not-exist")
    assert clarion_home() == Path.home() / "clarion"
