"""Tests for skills/clarion-thesis-monitor/scripts/monitor.py."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

from ai_buffett_zo.regime import RegimeSnapshot
from ai_buffett_zo.theses import HEALTH_COMPONENT_NAMES, parse_thesis_metadata

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    REPO_ROOT / "skills" / "clarion-thesis-monitor" / "scripts" / "monitor.py"
)


@pytest.fixture(scope="module")
def monitor_mod():
    spec = importlib.util.spec_from_file_location("clarion_monitor", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["clarion_monitor"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def troot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "theses"
    p.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLARION_THESES_ROOT", str(p))
    return p


def _regime(color: str = "orange") -> RegimeSnapshot:
    return RegimeSnapshot(
        asof=date(2026, 5, 6),
        color=color,  # type: ignore[arg-type]
        spy_ret_short=-0.025,
        tlt_ret_short=0.012,
        rsp_vs_spy_long=-0.060,
        spy_drawdown_from_high=-0.080,
        hurdle_rate_pct=None,
        rationale="rationale",
        breadth_flag="broad",
    )


def _patch(
    monitor_mod,
    monkeypatch: pytest.MonkeyPatch,
    *,
    regime_color: str = "orange",
    current_price: float | None = 100.0,
) -> None:
    monkeypatch.setattr(monitor_mod, "_resolve_regime", lambda: _regime(regime_color))
    monkeypatch.setattr(
        monitor_mod, "_current_price", lambda ticker, override=None: override or current_price
    )


def _args(
    *,
    ticker: str | None = None,
    quick: bool = False,
    no_write: bool = False,
    current_price: float | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        ticker=ticker,
        quick=quick,
        no_write=no_write,
        current_price=current_price,
    )


SAMPLE_THESIS = """\
# Thesis: NVDA — AI infrastructure compounder

---

## Metadata

```yaml
ticker: NVDA
company: NVIDIA Corporation
bucket: value
status: active
opened: 2024-01-15
last_reviewed: 2026-05-01
health_score: 78
cost_basis: 450.00
shares: 100
portfolio_weight: 9.5
base_case_fair_value: 480.0
catalyst_date: 2026-08-15
```

---

## Core Thesis

### What I Believe

NVDA dominates AI accelerator supply.

---

## Kill Conditions

| # | Kill Condition | How to Monitor | Last Checked |
|---|---------------|----------------|--------------|
| 1 | Gross margin < 60% | 10-Q quarterly | 2026-04-30 |
| 2 | Major customer loss | 8-K filings | 2026-04-30 |

---

## Health Scoring

| Component | Weight | Current Score | Notes |
|-----------|--------|---------------|-------|
| Valuation Safety | 25% | 70 | trades 8% under base case |
| Business Health | 20% | 90 | revenue +50% YoY |
| Insider Alignment | 10% | 65 | mixed Form 4 |
| Catalyst Proximity | 10% | 75 | earnings in 4 weeks |
| Thesis Integrity | 25% | 80 | evidence intact |
| Risk Environment | 10% | 60 | orange regime, value bucket |
| **Overall** | **100%** | **78** | |

---

## History

| Date | Event | Detail |
|------|-------|--------|
| 2024-01-15 | OPENED | Entry at $450 |
"""


SAMPLE_KILLED = SAMPLE_THESIS.replace(
    "| 1 | Gross margin < 60% | 10-Q quarterly | 2026-04-30 |",
    "| 1 | Gross margin < 60% | 10-Q quarterly | 2026-04-30 | triggered |",
)


def _write_thesis(troot: Path, name: str, content: str) -> Path:
    p = troot / f"{name}.md"
    p.write_text(content)
    return p


# ---- error paths ------------------------------------------------------------


def test_run_errors_when_no_theses(
    monitor_mod, troot: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(monitor_mod, monkeypatch)
    rc = monitor_mod.run(_args())
    assert rc == 1
    out = capsys.readouterr().out
    assert "THESIS_MONITOR_ERROR" in out


def test_run_errors_when_regime_unavailable(
    monitor_mod, troot: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_thesis(troot, "NVDA", SAMPLE_THESIS)
    monkeypatch.setattr(monitor_mod, "_resolve_regime", lambda: None)
    rc = monitor_mod.run(_args())
    assert rc == 1
    out = capsys.readouterr().out
    assert "regime unavailable" in out


def test_run_errors_when_only_inactive_theses(
    monitor_mod, troot: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inactive = SAMPLE_THESIS.replace("status: active", "status: closed")
    _write_thesis(troot, "NVDA", inactive)
    _patch(monitor_mod, monkeypatch)
    rc = monitor_mod.run(_args())
    assert rc == 1
    out = capsys.readouterr().out
    assert "no active theses" in out


def test_run_skips_draft_theses(
    monitor_mod, troot: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Drafts are scaffolds-in-progress — clarion-thesis-write opens them at
    status=draft so the dashboard isn't polluted by unfilled theses scoring
    near-zero. Monitor must skip drafts the same way it skips closed/killed."""
    draft = SAMPLE_THESIS.replace("status: active", "status: draft")
    _write_thesis(troot, "NVDA", draft)
    _patch(monitor_mod, monkeypatch)
    rc = monitor_mod.run(_args())
    assert rc == 1
    out = capsys.readouterr().out
    assert "no active theses" in out
    # Error message must mention drafts so users know what's going on.
    assert "draft" in out.lower()


def test_run_skips_draft_among_active_theses(
    monitor_mod, troot: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Mix of one draft + one active: dashboard renders only the active one."""
    draft_aapl = (
        SAMPLE_THESIS
        .replace("ticker: NVDA", "ticker: AAPL")
        .replace("# Thesis: NVDA", "# Thesis: AAPL")
        .replace("status: active", "status: draft")
    )
    _write_thesis(troot, "AAPL", draft_aapl)
    _write_thesis(troot, "NVDA", SAMPLE_THESIS)  # status: active
    _patch(monitor_mod, monkeypatch, current_price=440.0)

    rc = monitor_mod.run(_args())
    assert rc == 0
    out = capsys.readouterr().out
    # NVDA (active) renders; AAPL (draft) is skipped.
    assert "NVDA" in out
    assert "AAPL" not in out
    # And the dashboard reports exactly 1 active thesis, not 2.
    assert "**Active theses:** 1" in out


# ---- happy paths ------------------------------------------------------------


def test_run_full_mode_renders_dashboard_and_writes_back(
    monitor_mod, troot: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_thesis(troot, "NVDA", SAMPLE_THESIS)
    _patch(monitor_mod, monkeypatch, current_price=440.0)  # margin = (480-440)/480 = 8.3%

    rc = monitor_mod.run(_args())
    assert rc == 0
    out = capsys.readouterr().out
    assert "Thesis Health Dashboard" in out
    assert "NVDA" in out
    assert "ORANGE" in out

    # File was updated: last_reviewed should be today
    md = parse_thesis_metadata(path.read_text())
    assert md is not None
    assert md.last_reviewed == date.today()


def test_run_no_write_preserves_file(
    monitor_mod, troot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_thesis(troot, "NVDA", SAMPLE_THESIS)
    original = path.read_text()
    _patch(monitor_mod, monkeypatch)

    monitor_mod.run(_args(no_write=True))
    assert path.read_text() == original


def test_run_recomputes_risk_environment_per_regime(
    monitor_mod, troot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In green regime, value-bucket Risk Environment should be 80."""
    path = _write_thesis(troot, "NVDA", SAMPLE_THESIS)
    _patch(monitor_mod, monkeypatch, regime_color="green")

    monitor_mod.run(_args())
    content = path.read_text()
    # Find the Risk Environment row
    for line in content.splitlines():
        if "Risk Environment" in line and "|" in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            assert "80" in cells[2]
            break


def test_run_recomputes_valuation_safety_when_inputs_present(
    monitor_mod, troot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_thesis(troot, "NVDA", SAMPLE_THESIS)
    # base_case_fair_value=480 in metadata; price 240 → margin 50% → score 90
    _patch(monitor_mod, monkeypatch, current_price=240.0)
    monitor_mod.run(_args())
    content = path.read_text()
    for line in content.splitlines():
        if "Valuation Safety" in line and "|" in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            assert "90" in cells[2]
            break


def test_run_quick_mode_skips_valuation_recompute(
    monitor_mod, troot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_thesis(troot, "NVDA", SAMPLE_THESIS)
    _patch(monitor_mod, monkeypatch, current_price=240.0)
    monitor_mod.run(_args(quick=True))
    content = path.read_text()
    # Valuation Safety should still be 70 (carry-forward)
    for line in content.splitlines():
        if "Valuation Safety" in line and "|" in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            assert "70" in cells[2]
            break


def test_run_filters_to_single_ticker(
    monitor_mod, troot: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_thesis(troot, "NVDA", SAMPLE_THESIS)
    aapl_thesis = SAMPLE_THESIS.replace("NVDA", "AAPL").replace(
        "ticker: AAPL", "ticker: AAPL"
    )
    _write_thesis(troot, "AAPL", aapl_thesis)

    _patch(monitor_mod, monkeypatch)
    rc = monitor_mod.run(_args(ticker="NVDA"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "NVDA" in out


def test_run_includes_action_items_section_when_action_changes(
    monitor_mod, troot: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A thesis with very low scores should surface in Action Items."""
    low_thesis = SAMPLE_THESIS.replace(
        "| Valuation Safety | 25% | 70 | trades 8% under base case |",
        "| Valuation Safety | 25% | 20 | trades above fair value |",
    ).replace(
        "| Business Health | 20% | 90 | revenue +50% YoY |",
        "| Business Health | 20% | 25 | revenue declining |",
    ).replace(
        "| Thesis Integrity | 25% | 80 | evidence intact |",
        "| Thesis Integrity | 25% | 30 | core evidence weakened |",
    )
    _write_thesis(troot, "NVDA", low_thesis)
    _patch(monitor_mod, monkeypatch)
    monitor_mod.run(_args())
    out = capsys.readouterr().out
    assert "Action Items" in out
    assert "EXIT" in out or "REDUCE" in out


# ---- helper functions ------------------------------------------------------


def test_lowest_component_helper(monitor_mod) -> None:
    from ai_buffett_zo.theses import HealthComponent, HealthSnapshot

    components = [
        HealthComponent("A", 50, 80),
        HealthComponent("B", 50, 30),
    ]
    snap = HealthSnapshot(components=components, overall=55, action="HOLD")
    assert "B" in monitor_mod._lowest_component(snap)
    assert "30" in monitor_mod._lowest_component(snap)


def test_action_from_score_passthrough(monitor_mod) -> None:
    assert monitor_mod._action_from_score(80) == "ADD"
    assert monitor_mod._action_from_score(50) == "REDUCE"
    assert monitor_mod._action_from_score(None) is None


def test_health_components_in_template_match_canonical(monitor_mod) -> None:
    """Sanity: the canonical names list and the per-script imports agree."""
    from ai_buffett_zo.theses.types import HEALTH_COMPONENT_NAMES as canonical

    assert canonical == HEALTH_COMPONENT_NAMES
