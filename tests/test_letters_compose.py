"""Tests for ai_buffett_zo.letters.compose."""

from __future__ import annotations

from datetime import date

from ai_buffett_zo.letters import render_finalization, render_quarterly_section
from ai_buffett_zo.regime import RegimeSnapshot
from ai_buffett_zo.theses import ThesisMetadata


def _md(
    ticker: str,
    bucket: str = "value",
    status: str = "active",
    health: int | None = 70,
) -> ThesisMetadata:
    return ThesisMetadata(
        ticker=ticker,
        company=f"{ticker} Inc.",
        bucket=bucket,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        opened=date(2024, 1, 15),
        last_reviewed=date(2026, 5, 1),
        health_score=health,
    )


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


# ---- render_quarterly_section ---------------------------------------------


def test_quarterly_section_has_all_subsections() -> None:
    out = render_quarterly_section(
        quarter=2,
        update_date=date(2026, 5, 7),
        regime=_regime(),
        active_theses=[_md("NVDA"), _md("AAPL", "value", "active", 65)],
    )
    for header in [
        "**Updated: 2026-05-07**",
        "### Regime & Environment",
        "### Portfolio Snapshot",
        "### What We Did",
        "### Thesis Health",
        "### What We Learned",
        "### Performance",
    ]:
        assert header in out


def test_quarterly_section_regime_filled_when_available() -> None:
    out = render_quarterly_section(
        quarter=2,
        update_date=date(2026, 5, 7),
        regime=_regime(),
        active_theses=[],
    )
    assert "ORANGE" in out
    assert "flight to safety" in out


def test_quarterly_section_regime_todo_when_missing() -> None:
    out = render_quarterly_section(
        quarter=2,
        update_date=date(2026, 5, 7),
        regime=None,
        active_theses=[],
    )
    assert "[TODO" in out
    assert "regime-check unavailable" in out


def test_quarterly_section_thesis_health_table_lists_all_active() -> None:
    out = render_quarterly_section(
        quarter=2,
        update_date=date(2026, 5, 7),
        regime=_regime(),
        active_theses=[_md("NVDA", "value", "active", 78), _md("LULU", "value", "active", 55)],
    )
    assert "NVDA" in out
    assert "LULU" in out
    assert "78" in out
    assert "55" in out


def test_quarterly_section_thesis_health_no_active_message() -> None:
    out = render_quarterly_section(
        quarter=1,
        update_date=date(2026, 1, 31),
        regime=_regime(),
        active_theses=[],
    )
    assert "No active theses at this update" in out


def test_quarterly_section_portfolio_snapshot_groups_by_bucket() -> None:
    out = render_quarterly_section(
        quarter=2,
        update_date=date(2026, 5, 7),
        regime=_regime(),
        active_theses=[
            _md("NVDA", "value"),
            _md("AAPL", "value"),
            _md("HOOD", "yolo"),
            _md("TSLA", "short"),
        ],
    )
    # NVDA + AAPL appear in the Value row; HOOD in YOLO; TSLA in Short
    assert "NVDA, AAPL" in out or "AAPL, NVDA" in out
    assert "HOOD" in out
    assert "TSLA" in out


def test_quarterly_section_quarter_appears_in_performance() -> None:
    """Performance bullet should reference the quarter number."""
    out = render_quarterly_section(
        quarter=3,
        update_date=date(2026, 9, 30),
        regime=_regime(),
        active_theses=[],
    )
    assert "Q3" in out


# ---- render_finalization ---------------------------------------------------


def test_finalization_returns_year_in_context_and_summary() -> None:
    yic, summary = render_finalization(
        year=2026,
        finalize_date=date(2027, 1, 15),
        active_theses=[],
    )
    assert "[TODO" in yic
    assert "*Finalized: 2027-01-15*" in summary


def test_finalization_summary_has_required_sections() -> None:
    _, summary = render_finalization(
        year=2026,
        finalize_date=date(2027, 1, 15),
        active_theses=[],
    )
    for header in [
        "### Performance",
        "### By Bucket",
        "### Mistakes & Lessons",
        "### Theses: Final Scorecard",
        "### Looking Ahead",
    ]:
        assert header in summary


def test_finalization_scorecard_lists_theses() -> None:
    theses = [_md("NVDA", "value", "active", 80), _md("KO", "value", "closed", None)]
    _, summary = render_finalization(
        year=2026,
        finalize_date=date(2027, 1, 15),
        active_theses=theses,
    )
    assert "NVDA" in summary
    assert "KO" in summary
    assert "active" in summary
    assert "closed" in summary


def test_finalization_scorecard_todo_when_no_theses() -> None:
    _, summary = render_finalization(
        year=2026,
        finalize_date=date(2027, 1, 15),
        active_theses=[],
    )
    assert "[TODO No theses to score" in summary


def test_finalization_summary_period_line() -> None:
    _, summary = render_finalization(
        year=2026,
        finalize_date=date(2027, 1, 15),
        active_theses=[],
    )
    assert "2026-01-01" in summary
    assert "2026-12-31" in summary
