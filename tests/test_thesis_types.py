"""Tests for ai_buffett_zo.theses.types."""

from __future__ import annotations

from datetime import date

from ai_buffett_zo.theses import (
    DEFAULT_HEALTH_WEIGHTS,
    HEALTH_COMPONENT_NAMES,
    HealthComponent,
    HistoryEntry,
    KillCondition,
    ThesisMetadata,
    ValuationScenario,
)


def test_health_component_names_match_template() -> None:
    """The 6 canonical names from _TEMPLATE.md."""
    assert HEALTH_COMPONENT_NAMES == (
        "Valuation Safety",
        "Business Health",
        "Insider Alignment",
        "Catalyst Proximity",
        "Thesis Integrity",
        "Risk Environment",
    )


def test_default_health_weights_sum_to_100() -> None:
    assert sum(DEFAULT_HEALTH_WEIGHTS.values()) == 100


def test_default_health_weights_cover_all_components() -> None:
    assert set(DEFAULT_HEALTH_WEIGHTS.keys()) == set(HEALTH_COMPONENT_NAMES)


def test_thesis_metadata_minimal() -> None:
    md = ThesisMetadata(
        ticker="NVDA",
        company="NVIDIA",
        bucket="value",
        status="active",
        opened=date(2024, 1, 15),
    )
    assert md.ticker == "NVDA"
    assert md.health_score is None
    assert md.shares == 0


def test_health_component_default_notes() -> None:
    c = HealthComponent("Valuation Safety", 25, 60)
    assert c.notes == ""


def test_kill_condition_default_status_clear() -> None:
    k = KillCondition(description="x", monitoring="y")
    assert k.status == "clear"
    assert k.last_checked is None


def test_valuation_scenario_signed_upside() -> None:
    s = ValuationScenario(label="bear", assumptions="x", fair_value=400.0, upside_pct=-10.5)
    assert s.upside_pct == -10.5


def test_history_entry_required_fields() -> None:
    h = HistoryEntry(date=date(2026, 5, 7), event="OPENED", detail="initial entry")
    assert h.event == "OPENED"
