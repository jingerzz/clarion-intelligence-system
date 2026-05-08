"""Health scoring for active theses.

Implements the 6-component scoring from the AWB thesis-monitor framework
(see docs/PRINCIPLES.md, docs/ALLOCATION-POLICY.md, docs/DESIGN-LANGUAGE.md
and the inline citations below).

For directly-derivable components (Valuation Safety, Catalyst Proximity,
Risk Environment) we provide concrete scoring functions. The LLM-driven
components (Business Health, Insider Alignment, Thesis Integrity) accept
a precomputed score from the caller — the skill script does the LLM call
via /zo/ask and feeds the result back in. This keeps the lib deterministic
and offline-testable.
"""

from __future__ import annotations

from datetime import date

from ai_buffett_zo.theses.types import (
    Action,
    Bucket,
    HealthComponent,
    HealthSnapshot,
    KillCondition,
)

# ---- Component scoring -----------------------------------------------------


def score_valuation_safety(margin_of_safety_pct: float | None) -> int:
    """Score Valuation Safety based on margin of safety (base case fair value
    vs current price). Margin > 0 means current price is below fair value.

    Per the AWB thesis-monitor framework:
        margin > 40%   → 90
        margin > 25%   → 75
        margin > 10%   → 60
        margin > 0%    → 45
        margin < 0%    → 30  (above fair value)
        margin < -20%  → 15  (significantly above fair value)
    """
    if margin_of_safety_pct is None:
        return 55  # neutral default when we can't compute
    m = margin_of_safety_pct
    if m > 40:
        return 90
    if m > 25:
        return 75
    if m > 10:
        return 60
    if m > 0:
        return 45
    if m > -20:
        return 30
    return 15


def score_catalyst_proximity(days_to_catalyst: int | None) -> int:
    """Score Catalyst Proximity based on days to expected catalyst.

    Per AWB:
        within 30 days       → 85
        within 90 days       → 75
        within 180 days      → 60
        no defined catalyst  → 50  (patience-based)
        catalyst missed      → 35  (passed without materializing)
    """
    if days_to_catalyst is None:
        return 50  # patience-based thesis, no defined catalyst
    if days_to_catalyst < 0:
        return 35  # catalyst already passed without materializing
    if days_to_catalyst <= 30:
        return 85
    if days_to_catalyst <= 90:
        return 75
    if days_to_catalyst <= 180:
        return 60
    return 55  # >180 days, treat as patience-based with mild discount


# Risk Environment matrix: (bucket, regime_color) → score.
# Per AWB framework: shorts thrive in stress, value/yolo struggle in stress.
_RISK_MATRIX: dict[tuple[Bucket, str], int] = {
    ("value", "green"): 80,
    ("value", "blue"): 80,
    ("value", "orange"): 60,
    ("value", "red"): 40,
    ("value", "danger"): 30,
    ("systematic", "green"): 70,
    ("systematic", "blue"): 70,
    ("systematic", "orange"): 60,
    ("systematic", "red"): 50,
    ("systematic", "danger"): 40,
    ("short", "green"): 40,
    ("short", "blue"): 40,
    ("short", "orange"): 65,
    ("short", "red"): 85,
    ("short", "danger"): 85,
    ("yolo", "green"): 70,
    ("yolo", "blue"): 70,
    ("yolo", "orange"): 50,
    ("yolo", "red"): 35,
    ("yolo", "danger"): 30,
}


def score_risk_environment(bucket: Bucket, regime_color: str) -> int:
    """Score Risk Environment from regime × bucket compatibility."""
    key = (bucket, regime_color.lower())
    return _RISK_MATRIX.get(key, 55)


# ---- Overall score + action map -------------------------------------------


def overall_score(components: list[HealthComponent]) -> int:
    """Weighted average of component scores. Weights expected to sum to 100."""
    if not components:
        return 0
    total_weight = sum(c.weight for c in components)
    if total_weight == 0:
        return 0
    weighted = sum(c.score * c.weight for c in components)
    return int(round(weighted / total_weight))


# Action thresholds per AWB thesis-monitor framework.
def action_for_score(score: int) -> Action:
    if score < 40:
        return "EXIT"
    if score < 55:
        return "REDUCE"
    if score < 75:
        return "HOLD"
    return "ADD"


# Ordering for regime adjustments (downgrade = move toward EXIT).
_ACTION_LADDER: list[Action] = ["EXIT", "REDUCE", "HOLD", "ADD"]


def adjust_for_regime(action: Action, *, bucket: Bucket, regime_color: str) -> Action:
    """Apply the regime overrides from AWB thesis-monitor's Step 5.

    - DANGER state: all theses downgrade one level; shorts upgrade one.
    - RED regime: YOLO downgrades; shorts upgrade; others unchanged.
    - GREEN/BLUE/ORANGE: no adjustment.
    """
    color = regime_color.lower()
    if color == "danger":
        if bucket == "short":
            return _shift(action, +1)
        return _shift(action, -1)
    if color == "red":
        if bucket == "yolo":
            return _shift(action, -1)
        if bucket == "short":
            return _shift(action, +1)
    return action


def _shift(action: Action, delta: int) -> Action:
    idx = _ACTION_LADDER.index(action)
    new_idx = max(0, min(len(_ACTION_LADDER) - 1, idx + delta))
    return _ACTION_LADDER[new_idx]


# ---- Snapshot composition --------------------------------------------------


def evaluate(
    *,
    components: list[HealthComponent],
    bucket: Bucket,
    regime_color: str,
    kill_conditions: list[KillCondition] | None = None,
) -> HealthSnapshot:
    """Compose health components, kill-condition status, and regime adjustment
    into a single HealthSnapshot.

    Hard rule: if any kill condition has status='triggered', action is forced
    to EXIT regardless of score (and the snapshot's `kill_triggered` flag is
    set). This is the AWB framework's #1 hard rule.
    """
    overall = overall_score(components)
    base_action = action_for_score(overall)
    adjusted = adjust_for_regime(base_action, bucket=bucket, regime_color=regime_color)

    triggered = [k for k in (kill_conditions or []) if k.status == "triggered"]
    if triggered:
        return HealthSnapshot(
            components=components,
            overall=overall,
            action="EXIT",
            kill_triggered=True,
            kill_reasons=[k.description for k in triggered],
            rationale=(
                f"{len(triggered)} kill condition(s) triggered — EXIT overrides "
                f"the {overall}/100 score-derived action ({base_action})."
            ),
        )

    rationale_parts = [f"Overall {overall}/100 → {base_action}"]
    if adjusted != base_action:
        rationale_parts.append(
            f"adjusted to {adjusted} for {regime_color.upper()} regime / {bucket} bucket"
        )
    return HealthSnapshot(
        components=components,
        overall=overall,
        action=adjusted,
        rationale="; ".join(rationale_parts),
    )


# ---- Catalyst proximity helper --------------------------------------------


def days_until(target: date | None, *, asof: date | None = None) -> int | None:
    """Days from `asof` (default today) until `target`. Negative if past.

    Returns None when target is None — useful for patience-based theses where
    the thesis explicitly has no defined catalyst.
    """
    if target is None:
        return None
    asof = asof or date.today()
    return (target - asof).days
