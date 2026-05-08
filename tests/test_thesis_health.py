"""Tests for ai_buffett_zo.theses.health."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from ai_buffett_zo.theses import (
    HealthComponent,
    HealthSnapshot,
    KillCondition,
    action_for_score,
    adjust_for_regime,
    days_until,
    evaluate,
    overall_score,
    score_catalyst_proximity,
    score_risk_environment,
    score_valuation_safety,
)


# ---- score_valuation_safety ------------------------------------------------


@pytest.mark.parametrize(
    ("margin", "expected"),
    [
        (50.0, 90),    # > 40
        (30.0, 75),    # 25-40
        (15.0, 60),    # 10-25
        (5.0, 45),     # 0-10
        (-5.0, 30),    # 0 to -20
        (-25.0, 15),   # < -20
    ],
)
def test_score_valuation_safety_buckets(margin: float, expected: int) -> None:
    assert score_valuation_safety(margin) == expected


def test_score_valuation_safety_none_returns_neutral() -> None:
    assert score_valuation_safety(None) == 55


# ---- score_catalyst_proximity ----------------------------------------------


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (15, 85),    # within 30
        (60, 75),    # within 90
        (150, 60),   # within 180
        (200, 55),   # patience-ish
        (-10, 35),   # missed
    ],
)
def test_score_catalyst_proximity(days: int, expected: int) -> None:
    assert score_catalyst_proximity(days) == expected


def test_score_catalyst_proximity_none_is_patience_default() -> None:
    assert score_catalyst_proximity(None) == 50


# ---- score_risk_environment ------------------------------------------------


@pytest.mark.parametrize(
    ("bucket", "color", "expected"),
    [
        ("value", "green", 80),
        ("value", "blue", 80),
        ("value", "orange", 60),
        ("value", "red", 40),
        ("value", "danger", 30),
        ("short", "danger", 85),
        ("short", "red", 85),
        ("short", "green", 40),
        ("yolo", "danger", 30),
        ("yolo", "green", 70),
        ("systematic", "orange", 60),
    ],
)
def test_score_risk_environment(bucket: str, color: str, expected: int) -> None:
    assert score_risk_environment(bucket, color) == expected  # type: ignore[arg-type]


def test_score_risk_environment_unknown_returns_neutral() -> None:
    assert score_risk_environment("value", "unknown") == 55  # type: ignore[arg-type]


# ---- overall_score ---------------------------------------------------------


def test_overall_score_weighted_average() -> None:
    components = [
        HealthComponent("A", 50, 80),
        HealthComponent("B", 50, 60),
    ]
    assert overall_score(components) == 70


def test_overall_score_irregular_weights() -> None:
    components = [
        HealthComponent("A", 30, 90),
        HealthComponent("B", 70, 50),
    ]
    # (30*90 + 70*50) / 100 = 2700+3500 / 100 = 62
    assert overall_score(components) == 62


def test_overall_score_empty() -> None:
    assert overall_score([]) == 0


def test_overall_score_zero_weights() -> None:
    assert overall_score([HealthComponent("A", 0, 90)]) == 0


# ---- action_for_score ------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0, "EXIT"),
        (39, "EXIT"),
        (40, "REDUCE"),
        (54, "REDUCE"),
        (55, "HOLD"),
        (74, "HOLD"),
        (75, "ADD"),
        (100, "ADD"),
    ],
)
def test_action_for_score_thresholds(score: int, expected: str) -> None:
    assert action_for_score(score) == expected


# ---- adjust_for_regime -----------------------------------------------------


def test_adjust_for_regime_danger_downgrades_value() -> None:
    assert adjust_for_regime("ADD", bucket="value", regime_color="danger") == "HOLD"
    assert adjust_for_regime("HOLD", bucket="value", regime_color="danger") == "REDUCE"
    assert adjust_for_regime("REDUCE", bucket="value", regime_color="danger") == "EXIT"
    assert adjust_for_regime("EXIT", bucket="value", regime_color="danger") == "EXIT"  # floor


def test_adjust_for_regime_danger_upgrades_short() -> None:
    assert adjust_for_regime("HOLD", bucket="short", regime_color="danger") == "ADD"
    assert adjust_for_regime("ADD", bucket="short", regime_color="danger") == "ADD"  # ceiling


def test_adjust_for_regime_red_downgrades_yolo_upgrades_short() -> None:
    assert adjust_for_regime("HOLD", bucket="yolo", regime_color="red") == "REDUCE"
    assert adjust_for_regime("HOLD", bucket="short", regime_color="red") == "ADD"
    # Value/systematic unchanged in red
    assert adjust_for_regime("HOLD", bucket="value", regime_color="red") == "HOLD"


def test_adjust_for_regime_green_no_change() -> None:
    assert adjust_for_regime("ADD", bucket="value", regime_color="green") == "ADD"
    assert adjust_for_regime("HOLD", bucket="yolo", regime_color="green") == "HOLD"


# ---- evaluate (composition) -----------------------------------------------


def _comps(*scores: int) -> list[HealthComponent]:
    weights = (25, 20, 10, 10, 25, 10)
    names = ("VS", "BH", "IA", "CP", "TI", "RE")
    return [HealthComponent(n, w, s) for n, w, s in zip(names, weights, scores, strict=False)]


def test_evaluate_clean_path() -> None:
    snap = evaluate(
        components=_comps(80, 80, 80, 80, 80, 80),
        bucket="value",
        regime_color="green",
    )
    assert isinstance(snap, HealthSnapshot)
    assert snap.overall == 80
    assert snap.action == "ADD"
    assert snap.kill_triggered is False
    assert "ADD" in snap.rationale


def test_evaluate_kill_overrides_score() -> None:
    snap = evaluate(
        components=_comps(80, 80, 80, 80, 80, 80),
        bucket="value",
        regime_color="green",
        kill_conditions=[
            KillCondition("Margin compression", "10-Q", date(2026, 5, 7), status="triggered")
        ],
    )
    assert snap.kill_triggered is True
    assert snap.action == "EXIT"
    assert "Margin compression" in snap.kill_reasons
    assert "EXIT overrides" in snap.rationale


def test_evaluate_clear_kill_conditions_dont_override() -> None:
    snap = evaluate(
        components=_comps(80, 80, 80, 80, 80, 80),
        bucket="value",
        regime_color="green",
        kill_conditions=[
            KillCondition("Margin compression", "10-Q", date(2026, 5, 7), status="clear")
        ],
    )
    assert snap.kill_triggered is False
    assert snap.action == "ADD"


def test_evaluate_regime_adjustment_applied() -> None:
    snap = evaluate(
        components=_comps(80, 80, 80, 80, 80, 80),  # overall 80 → ADD
        bucket="value",
        regime_color="danger",
    )
    assert snap.action == "HOLD"  # downgraded one level
    assert "DANGER" in snap.rationale
    assert "value" in snap.rationale


# ---- days_until ------------------------------------------------------------


def test_days_until_today_is_zero() -> None:
    assert days_until(date.today()) == 0


def test_days_until_future() -> None:
    target = date.today() + timedelta(days=10)
    assert days_until(target) == 10


def test_days_until_past_is_negative() -> None:
    target = date.today() - timedelta(days=5)
    assert days_until(target) == -5


def test_days_until_none_returns_none() -> None:
    assert days_until(None) is None


def test_days_until_explicit_asof() -> None:
    assert days_until(date(2026, 5, 30), asof=date(2026, 5, 7)) == 23
