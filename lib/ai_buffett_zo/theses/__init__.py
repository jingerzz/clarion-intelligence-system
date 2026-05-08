"""Thesis types, I/O, and health scoring.

Reused by clarion-thesis-write (scaffolds new theses) and
clarion-thesis-monitor (reads, scores, updates active theses).
"""

from ai_buffett_zo.theses.health import (
    action_for_score,
    adjust_for_regime,
    days_until,
    evaluate,
    overall_score,
    score_catalyst_proximity,
    score_risk_environment,
    score_valuation_safety,
)
from ai_buffett_zo.theses.io import (
    DEFAULT_THESES_ROOT,
    append_history_entry,
    find_section_table,
    list_theses,
    parse_health_components,
    parse_kill_conditions,
    parse_metadata_block,
    parse_thesis_metadata,
    thesis_path,
    update_health_table,
    update_kill_conditions_last_checked,
    update_metadata_block,
)
from ai_buffett_zo.theses.types import (
    DEFAULT_HEALTH_WEIGHTS,
    HEALTH_COMPONENT_NAMES,
    Action,
    Bucket,
    HealthComponent,
    HealthSnapshot,
    HistoryEntry,
    KillCondition,
    KillStatus,
    Status,
    ThesisMetadata,
    ValuationScenario,
)

__all__ = [
    "Action",
    "Bucket",
    "DEFAULT_HEALTH_WEIGHTS",
    "DEFAULT_THESES_ROOT",
    "HEALTH_COMPONENT_NAMES",
    "HealthComponent",
    "HealthSnapshot",
    "HistoryEntry",
    "KillCondition",
    "KillStatus",
    "Status",
    "ThesisMetadata",
    "ValuationScenario",
    "action_for_score",
    "adjust_for_regime",
    "append_history_entry",
    "days_until",
    "evaluate",
    "find_section_table",
    "list_theses",
    "overall_score",
    "parse_health_components",
    "parse_kill_conditions",
    "parse_metadata_block",
    "parse_thesis_metadata",
    "score_catalyst_proximity",
    "score_risk_environment",
    "score_valuation_safety",
    "thesis_path",
    "update_health_table",
    "update_kill_conditions_last_checked",
    "update_metadata_block",
]
