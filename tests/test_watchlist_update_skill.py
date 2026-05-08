"""Tests for skills/clarion-watchlist-update/scripts/update.py."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "skills" / "clarion-watchlist-update" / "scripts" / "update.py"


@pytest.fixture(scope="module")
def update_mod():
    spec = importlib.util.spec_from_file_location("clarion_update", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["clarion_update"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    wl_root = tmp_path / "watchlists"
    th_root = tmp_path / "theses"
    wl_root.mkdir(parents=True, exist_ok=True)
    th_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLARION_WATCHLIST_ROOT", str(wl_root))
    monkeypatch.setenv("CLARION_THESES_ROOT", str(th_root))
    return wl_root, th_root


SAMPLE_WATCHLIST = """\
# S&P 500 Value Screen — 2026-05-07

## Context

- **Regime**: ORANGE
- **Hurdle Rate**: 10.45%

## Stage 1 Ranked Results — Top 3 (Raw Composite, Pre Sector Cap)

| Rank | Ticker | Sector | Score | P/E | P/FCF | ROE% | ROIC% | OpM% | D/E | ProfM% | Insider% | Mkt Cap | Price |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | NVDA | Tech | **75.5** | 18.00 | 14.00 | 25.0 | 20.0 | 30.0 | 0.30 | 22.0 | +2.0 | $3T | $140.00 |
| 2 | AAPL | Tech | 65.0 | 22.00 | 18.00 | 30.0 | 22.0 | 28.0 | 0.50 | 25.0 | -1.0 | $3T | $200.00 |
| 3 | ADBE | Tech | 55.0 | 25.00 | 20.00 | 35.0 | 25.0 | 35.0 | 0.40 | 30.0 | -0.5 | $200B | $300.00 |

## Top 3 After Sector Cap (Max 3 per GICS)

| Rank | Ticker | Sector | Score |
| --- | --- | --- | --- |
| 1 | NVDA | Tech | 75.5 |
| 2 | AAPL | Tech | 65.0 |
| 3 | ADBE | Tech | 55.0 |

## Sniff Test: New Names Worth a Stage 2 Deep Dive

[TODO]

## Passed On (Notable)

[TODO]

## Existing Theses Impact

[TODO]
"""


def _write_watchlist(root: Path, screen_date: date, content: str = SAMPLE_WATCHLIST) -> Path:
    p = root / f"sp500-screen-{screen_date.isoformat()}.md"
    p.write_text(content)
    return p


def _args(
    *,
    top_only: bool = False,
    top_size: int = 10,
    threshold_pct: float = 10.0,
    max_stale_days: int = 14,
) -> argparse.Namespace:
    return argparse.Namespace(
        top_only=top_only,
        top_size=top_size,
        threshold_pct=threshold_pct,
        max_stale_days=max_stale_days,
    )


def _patch_prices(update_mod, monkeypatch: pytest.MonkeyPatch, prices: dict[str, float | None]) -> None:
    monkeypatch.setattr(
        update_mod, "_current_price", lambda ticker: prices.get(ticker.upper())
    )


# ---- error paths ------------------------------------------------------------


def test_run_errors_when_no_watchlists(
    update_mod, roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    rc = update_mod.run(_args())
    assert rc == 1
    assert "WATCHLIST_UPDATE_ERROR" in capsys.readouterr().out


def test_run_errors_when_unparseable(
    update_mod, roots: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    wl_root, _ = roots
    _write_watchlist(wl_root, date.today(), content="# Not a real watchlist\n")
    rc = update_mod.run(_args())
    assert rc == 1
    assert "unparseable" in capsys.readouterr().out


# ---- happy paths ------------------------------------------------------------


def test_run_renders_full_table(
    update_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wl_root, _ = roots
    _write_watchlist(wl_root, date.today())
    _patch_prices(update_mod, monkeypatch, {"NVDA": 150.0, "AAPL": 195.0, "ADBE": 310.0})

    rc = update_mod.run(_args())
    assert rc == 0
    out = capsys.readouterr().out
    assert "Watchlist Update" in out
    assert "NVDA" in out
    assert "AAPL" in out
    assert "Full ranked list" in out


def test_run_flags_big_movers(
    update_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wl_root, _ = roots
    _write_watchlist(wl_root, date.today())
    # NVDA from 140 → 168 (+20%); AAPL flat
    _patch_prices(update_mod, monkeypatch, {"NVDA": 168.0, "AAPL": 200.0, "ADBE": 300.0})

    update_mod.run(_args(threshold_pct=10.0))
    out = capsys.readouterr().out
    assert "Big movers" in out
    assert "NVDA" in out
    assert "+20.0%" in out
    assert "entry case weaker" in out


def test_run_flags_negative_movers_as_fresh_look(
    update_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wl_root, _ = roots
    _write_watchlist(wl_root, date.today())
    # NVDA from 140 → 112 (-20%)
    _patch_prices(update_mod, monkeypatch, {"NVDA": 112.0, "AAPL": 200.0, "ADBE": 300.0})

    update_mod.run(_args())
    out = capsys.readouterr().out
    assert "Big movers" in out
    assert "NVDA" in out
    assert "-20.0%" in out
    assert "worth a fresh look" in out


def test_run_no_movers_section_when_all_quiet(
    update_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wl_root, _ = roots
    _write_watchlist(wl_root, date.today())
    _patch_prices(update_mod, monkeypatch, {"NVDA": 142.0, "AAPL": 198.0, "ADBE": 305.0})

    update_mod.run(_args())
    out = capsys.readouterr().out
    assert "Big movers" not in out


def test_run_flags_stale_when_old(
    update_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wl_root, _ = roots
    _write_watchlist(wl_root, date.today() - timedelta(days=30))
    _patch_prices(update_mod, monkeypatch, {"NVDA": 140.0, "AAPL": 200.0, "ADBE": 300.0})

    update_mod.run(_args(max_stale_days=14))
    out = capsys.readouterr().out
    assert "stale" in out.lower()
    assert "clarion-value-screener" in out


def test_run_no_stale_warning_when_fresh(
    update_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wl_root, _ = roots
    _write_watchlist(wl_root, date.today())
    _patch_prices(update_mod, monkeypatch, {"NVDA": 140.0, "AAPL": 200.0, "ADBE": 300.0})

    update_mod.run(_args())
    out = capsys.readouterr().out
    assert "stale" not in out.lower() or "**stale**" not in out


def test_run_top_only_filters_to_top_size(
    update_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wl_root, _ = roots
    _write_watchlist(wl_root, date.today())
    _patch_prices(update_mod, monkeypatch, {"NVDA": 140.0, "AAPL": 200.0, "ADBE": 300.0})

    update_mod.run(_args(top_only=True, top_size=2))
    out = capsys.readouterr().out
    assert "Top-N (sector-capped)" in out
    # Only first 2 rows should appear in the full table
    table_after_label = out.split("Top-N (sector-capped)", 1)[1]
    assert "NVDA" in table_after_label
    assert "AAPL" in table_after_label


def test_run_includes_watchlist_status_theses(
    update_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wl_root, th_root = roots
    _write_watchlist(wl_root, date.today())

    thesis = """\
# Thesis: LULU — fallen angel

## Metadata

```yaml
ticker: LULU
company: Lululemon
bucket: value
status: watchlist
opened: 2026-01-15
cost_basis: 138.00
shares: 0
```

## Health Scoring

| Component | Weight | Current Score | Notes |
|-----------|--------|---------------|-------|
| **Overall** | **100%** | **55** | |
"""
    (th_root / "LULU.md").write_text(thesis)

    _patch_prices(
        update_mod, monkeypatch, {"NVDA": 140.0, "AAPL": 200.0, "ADBE": 300.0, "LULU": 115.0}
    )
    update_mod.run(_args())
    out = capsys.readouterr().out
    assert "Watchlist-status theses" in out
    assert "LULU" in out
    assert "$138.00" in out
    assert "$115.00" in out


def test_run_skips_active_status_theses(
    update_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wl_root, th_root = roots
    _write_watchlist(wl_root, date.today())

    thesis = """\
# Thesis: NVDA

## Metadata

```yaml
ticker: NVDA
company: NVIDIA
bucket: value
status: active
opened: 2024-01-15
```

## Health Scoring

| Component | Weight | Current Score | Notes |
|-----------|--------|---------------|-------|
| **Overall** | **100%** | **70** | |
"""
    (th_root / "NVDA.md").write_text(thesis)

    _patch_prices(update_mod, monkeypatch, {"NVDA": 140.0, "AAPL": 200.0, "ADBE": 300.0})
    update_mod.run(_args())
    out = capsys.readouterr().out
    # No watchlist-status section since the only thesis is active
    assert "Watchlist-status theses" not in out


# ---- helpers ---------------------------------------------------------------


def test_date_from_filename(update_mod) -> None:
    assert update_mod._date_from_filename(Path("sp500-screen-2026-05-07.md")) == date(2026, 5, 7)
    assert update_mod._date_from_filename(Path("notes.md")) is None


def test_fmt_signed_pct(update_mod) -> None:
    assert update_mod._fmt_signed_pct(None) == "n/a"
    assert update_mod._fmt_signed_pct(5.5) == "+5.5%"
    assert update_mod._fmt_signed_pct(-3.2) == "-3.2%"


def test_move_vs_basis(update_mod) -> None:
    assert update_mod._move_vs_basis(100.0, 110.0) == "+10.0%"
    assert update_mod._move_vs_basis(None, 100.0) == "n/a"
    assert update_mod._move_vs_basis(0, 100.0) == "n/a"
