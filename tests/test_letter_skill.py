"""Tests for skills/clarion-living-letter-update/scripts/letter.py."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

from ai_buffett_zo.letters import (
    is_finalized,
    is_quarter_populated,
    letter_path,
)
from ai_buffett_zo.regime import RegimeSnapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "skills" / "clarion-living-letter-update" / "scripts" / "letter.py"


@pytest.fixture(scope="module")
def letter_mod():
    spec = importlib.util.spec_from_file_location("clarion_letter", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["clarion_letter"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    lroot = tmp_path / "letters"
    troot = tmp_path / "theses"
    lroot.mkdir(parents=True, exist_ok=True)
    troot.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLARION_LETTERS_ROOT", str(lroot))
    monkeypatch.setenv("CLARION_THESES_ROOT", str(troot))
    return lroot, troot


def _regime() -> RegimeSnapshot:
    return RegimeSnapshot(
        asof=date(2026, 5, 7),
        color="orange",
        spy_ret_short=-0.025,
        tlt_ret_short=0.012,
        rsp_vs_spy_long=-0.060,
        spy_drawdown_from_high=-0.080,
        hurdle_rate_pct=None,
        rationale="flight to safety",
    )


def _patch(letter_mod, monkeypatch: pytest.MonkeyPatch, *, regime=None, theses=None) -> None:
    monkeypatch.setattr(letter_mod, "_resolve_regime", lambda: regime if regime is not None else _regime())
    monkeypatch.setattr(letter_mod, "_active_theses", lambda: theses or [])
    monkeypatch.setattr(letter_mod, "_all_theses", lambda: theses or [])


def _args_update(*, year: int | None = 2026, quarter: int | None = 2, force: bool = False) -> argparse.Namespace:
    return argparse.Namespace(year=year, quarter=quarter, force=force)


def _args_finalize(*, year: int | None = 2026, force: bool = False) -> argparse.Namespace:
    return argparse.Namespace(year=year, force=force)


def _args_status(*, year: int | None = 2026) -> argparse.Namespace:
    return argparse.Namespace(year=year)


# ---- update -----------------------------------------------------------------


def test_update_creates_letter_when_missing(
    letter_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(letter_mod, monkeypatch)
    lroot, _ = roots

    rc = letter_mod.cmd_update(_args_update())
    assert rc == 0
    p = letter_path(lroot, 2026)
    assert p.exists()
    content = p.read_text()
    assert is_quarter_populated(content, 2) is True
    assert is_quarter_populated(content, 1) is False
    out = capsys.readouterr().out
    assert "Wrote Q2 2026" in out


def test_update_refuses_to_overwrite_populated_quarter(
    letter_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(letter_mod, monkeypatch)

    letter_mod.cmd_update(_args_update())
    capsys.readouterr()  # clear

    rc = letter_mod.cmd_update(_args_update())
    assert rc == 1
    out = capsys.readouterr().out
    assert "LETTER_ERROR" in out
    assert "already populated" in out


def test_update_force_overwrites(
    letter_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(letter_mod, monkeypatch)

    letter_mod.cmd_update(_args_update())
    rc = letter_mod.cmd_update(_args_update(force=True))
    assert rc == 0


def test_update_unknown_quarter_errors(
    letter_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(letter_mod, monkeypatch)
    rc = letter_mod.cmd_update(_args_update(quarter=5))
    assert rc == 1
    assert "unknown quarter" in capsys.readouterr().out


def test_update_warns_when_regime_unavailable(
    letter_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(letter_mod, "_resolve_regime", lambda: None)
    monkeypatch.setattr(letter_mod, "_active_theses", lambda: [])
    monkeypatch.setattr(letter_mod, "_all_theses", lambda: [])

    rc = letter_mod.cmd_update(_args_update())
    assert rc == 0
    out = capsys.readouterr().out
    assert "regime unavailable" in out


# ---- finalize ---------------------------------------------------------------


def test_finalize_refuses_when_quarters_placeholders(
    letter_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(letter_mod, monkeypatch)

    rc = letter_mod.cmd_finalize(_args_finalize())
    assert rc == 1
    out = capsys.readouterr().out
    assert "cannot finalize" in out


def test_finalize_succeeds_when_all_quarters_populated(
    letter_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(letter_mod, monkeypatch)

    for q in (1, 2, 3, 4):
        letter_mod.cmd_update(_args_update(quarter=q))
    capsys.readouterr()

    rc = letter_mod.cmd_finalize(_args_finalize())
    assert rc == 0
    out = capsys.readouterr().out
    assert "Finalization scaffold written" in out

    lroot, _ = roots
    content = letter_path(lroot, 2026).read_text()
    assert is_finalized(content) is True


def test_finalize_force_skips_quarter_check(
    letter_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(letter_mod, monkeypatch)
    rc = letter_mod.cmd_finalize(_args_finalize(force=True))
    assert rc == 0


# ---- status ----------------------------------------------------------------


def test_status_no_letter(
    letter_mod, roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    rc = letter_mod.cmd_status(_args_status())
    assert rc == 0
    out = capsys.readouterr().out
    assert "No letter for 2026 yet" in out


def test_status_shows_per_quarter_state(
    letter_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(letter_mod, monkeypatch)
    letter_mod.cmd_update(_args_update(quarter=2))
    capsys.readouterr()

    rc = letter_mod.cmd_status(_args_status())
    assert rc == 0
    out = capsys.readouterr().out
    assert "Q1: January — March" in out
    assert "Q2: April — June" in out
    assert "✓ populated" in out  # at least Q2
    assert "placeholder" in out
    assert "not finalized" in out
