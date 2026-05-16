"""Tests for ai_buffett_zo.theses.io."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ai_buffett_zo.theses import (
    HealthComponent,
    HistoryEntry,
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


SAMPLE = """\
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
health_score: 78  # Must equal Overall row in body
cost_basis: 450.00
shares: 100
portfolio_weight: 9.5
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
| 2025-08-10 | THESIS UPDATED | Added data center segment evidence |
"""


SAMPLE_YAML_STRUCTURED = """\
# Thesis: PWR — Infrastructure contractor (grid modernization compounder)

---

## Metadata

```yaml
ticker: PWR
company: Quanta Services Inc
bucket: value
status: active
opened: 2026-05-16
last_reviewed: 2026-05-16
health_score: 72
cost_basis: 208.00
shares: 10
portfolio_weight: 5.0
base_case_fair_value: 280
catalyst_date: 2026-08-06

kill_conditions:
  - trigger: Revenue growth drops below 5% YoY for two consecutive quarters
    monitor: Quarterly 10-Q
    last_checked: '2026-05-16'
    status: clear
  - trigger: Major grid modernization contract loss (top-3 customer)
    monitor: 8-K filings
    last_checked: '2026-05-16'
    status: clear
  - trigger: Debt/EBITDA exceeds 3.5x
    monitor: Quarterly 10-Q
    last_checked: '2026-05-16'
    status: warning

health_components:
  - name: Valuation Safety
    weight: 25
    score: 72
    notes: trades ~26% under base case
  - name: Business Health
    weight: 20
    score: 85
    notes: revenue +12% YoY
  - name: Insider Alignment
    weight: 10
    score: 60
    notes: mixed Form 4 activity
  - name: Catalyst Proximity
    weight: 10
    score: 70
    notes: earnings in 82 days
  - name: Thesis Integrity
    weight: 25
    score: 75
    notes: infrastructure megatrend intact
  - name: Risk Environment
    weight: 10
    score: 60
    notes: orange regime, value bucket
```

---

## Kill Conditions

| # | Kill Condition | How to Monitor | Last Checked |
|---|---------------|----------------|-----------|
| 1 | [Backward compat fallback] | see YAML | YYYY-MM-DD |

---

## Health Scoring

| Component | Weight | Current Score | Notes |
|-----------|--------|---------------|-------|
| Valuation Safety | 25% | 10 | fallback — should be ignored |
| **Overall** | **100%** | **10** | |

---

## History

| Date | Event | Detail |
|------|-------|--------|
| 2026-05-16 | OPENED | Entry |
"""


# ---- parse_metadata_block --------------------------------------------------


def test_parse_metadata_block_extracts_yaml_keys() -> None:
    raw = parse_metadata_block(SAMPLE)
    assert raw["ticker"] == "NVDA"
    assert raw["company"] == "NVIDIA Corporation"
    assert raw["bucket"] == "value"
    assert raw["status"] == "active"
    assert raw["health_score"] == 78           # yaml.safe_load returns int
    assert raw["cost_basis"] == 450.0          # yaml.safe_load returns float


def test_parse_metadata_block_strips_inline_comments() -> None:
    raw = parse_metadata_block(SAMPLE)
    # health_score line had "# Must equal Overall row..." — yaml strips comments
    assert raw["health_score"] == 78
    assert "Must" not in str(raw["health_score"])


def test_parse_metadata_block_missing_returns_empty() -> None:
    assert parse_metadata_block("# No metadata here") == {}


# ---- parse_thesis_metadata ------------------------------------------------


def test_parse_thesis_metadata_full() -> None:
    md = parse_thesis_metadata(SAMPLE)
    assert md is not None
    assert md.ticker == "NVDA"
    assert md.company == "NVIDIA Corporation"
    assert md.bucket == "value"
    assert md.status == "active"
    assert md.opened == date(2024, 1, 15)
    assert md.last_reviewed == date(2026, 5, 1)
    assert md.health_score == 78
    assert md.cost_basis == 450.00
    assert md.shares == 100
    assert md.portfolio_weight == 9.5


def test_parse_thesis_metadata_uppercases_ticker() -> None:
    sample = SAMPLE.replace("ticker: NVDA", "ticker: nvda")
    md = parse_thesis_metadata(sample)
    assert md is not None
    assert md.ticker == "NVDA"


def test_parse_thesis_metadata_returns_none_on_missing_required() -> None:
    bare = "# Thesis: Bare\n\n```yaml\nticker: X\n```\n"
    assert parse_thesis_metadata(bare) is None


# ---- update_metadata_block -------------------------------------------------


def test_update_metadata_block_replaces_value() -> None:
    new = update_metadata_block(SAMPLE, {"health_score": 65})
    md = parse_thesis_metadata(new)
    assert md is not None
    assert md.health_score == 65


def test_update_metadata_block_preserves_inline_comment() -> None:
    new = update_metadata_block(SAMPLE, {"health_score": 60})
    assert "Must equal Overall row" in new


def test_update_metadata_block_replaces_date() -> None:
    new = update_metadata_block(SAMPLE, {"last_reviewed": date(2026, 5, 7)})
    md = parse_thesis_metadata(new)
    assert md is not None
    assert md.last_reviewed == date(2026, 5, 7)


def test_update_metadata_block_appends_new_key() -> None:
    new = update_metadata_block(SAMPLE, {"new_field": "new_value"})
    raw = parse_metadata_block(new)
    assert raw.get("new_field") == "new_value"


def test_update_metadata_block_missing_block_returns_unchanged() -> None:
    content = "# No yaml here"
    assert update_metadata_block(content, {"x": "y"}) == content


def test_update_metadata_block_preserves_other_keys() -> None:
    new = update_metadata_block(SAMPLE, {"health_score": 65})
    raw = parse_metadata_block(new)
    # All original fields still present
    for key in ("ticker", "company", "bucket", "status", "opened", "cost_basis"):
        assert key in raw


# ---- find_section_table ----------------------------------------------------


def test_find_section_table_locates_kill_conditions() -> None:
    found = find_section_table(
        SAMPLE,
        section_header="Kill Conditions",
        expected_columns=("kill condition",),
    )
    assert found is not None
    start, end, lines = found
    # Header row contains "Kill Condition"
    assert "Kill Condition" in lines[start]
    # 4 data rows would mean end = start + 2 (header + dashes) + 2 data = start + 4
    assert end - start >= 3  # at least header + dashes + 1 data row


def test_find_section_table_missing_section() -> None:
    content = "# Header only\n\n## Other\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    assert find_section_table(content, section_header="Kill Conditions", expected_columns=("x",)) is None


# ---- parse_kill_conditions -------------------------------------------------


def test_parse_kill_conditions_two_rows() -> None:
    kills = parse_kill_conditions(SAMPLE)
    assert len(kills) == 2
    assert kills[0].description == "Gross margin < 60%"
    assert kills[0].monitoring == "10-Q quarterly"
    assert kills[0].last_checked == date(2026, 4, 30)
    assert kills[1].description == "Major customer loss"


def test_parse_kill_conditions_skips_template_placeholders() -> None:
    template_text = """\
## Kill Conditions

| # | Kill Condition | How to Monitor | Last Checked |
|---|---------------|----------------|--------------|
| 1 | [Specific, measurable condition] | [MCP tool or data source] | [date] |
"""
    assert parse_kill_conditions(template_text) == []


# ---- parse_health_components ----------------------------------------------


def test_parse_health_components_six_rows_plus_overall() -> None:
    comps, overall = parse_health_components(SAMPLE)
    assert len(comps) == 6
    assert {c.name for c in comps} == {
        "Valuation Safety",
        "Business Health",
        "Insider Alignment",
        "Catalyst Proximity",
        "Thesis Integrity",
        "Risk Environment",
    }
    assert overall == 78


def test_parse_health_components_weights_and_scores() -> None:
    comps, _ = parse_health_components(SAMPLE)
    bh = next(c for c in comps if c.name == "Business Health")
    assert bh.weight == 20
    assert bh.score == 90
    assert "revenue +50% YoY" in bh.notes


# ---- update_health_table ---------------------------------------------------


def test_update_health_table_writes_new_scores() -> None:
    new_components = [
        HealthComponent("Valuation Safety", 25, 60),
        HealthComponent("Business Health", 20, 50),
        HealthComponent("Insider Alignment", 10, 70),
        HealthComponent("Catalyst Proximity", 10, 75),
        HealthComponent("Thesis Integrity", 25, 80),
        HealthComponent("Risk Environment", 10, 60),
    ]
    new = update_health_table(SAMPLE, new_components, overall=66)
    parsed_comps, parsed_overall = parse_health_components(new)
    assert parsed_overall == 66
    assert len(parsed_comps) == 6
    vs = next(c for c in parsed_comps if c.name == "Valuation Safety")
    assert vs.score == 60


def test_update_health_table_preserves_other_sections() -> None:
    new_components = [
        HealthComponent(name, w, 50)
        for name, w in [
            ("Valuation Safety", 25),
            ("Business Health", 20),
            ("Insider Alignment", 10),
            ("Catalyst Proximity", 10),
            ("Thesis Integrity", 25),
            ("Risk Environment", 10),
        ]
    ]
    new = update_health_table(SAMPLE, new_components, overall=50)
    # Kill conditions section still intact
    kills = parse_kill_conditions(new)
    assert len(kills) == 2
    # Title still intact
    assert "AI infrastructure compounder" in new


# ---- update_kill_conditions_last_checked -----------------------------------


def test_update_kill_conditions_last_checked_updates_all() -> None:
    when = date(2026, 5, 7)
    new = update_kill_conditions_last_checked(SAMPLE, when)
    kills = parse_kill_conditions(new)
    assert all(k.last_checked == when for k in kills)


# ---- append_history_entry --------------------------------------------------


def test_append_history_entry_adds_row() -> None:
    entry = HistoryEntry(date=date(2026, 5, 7), event="ACTION CHANGED", detail="HOLD → REDUCE")
    new = append_history_entry(SAMPLE, entry)
    assert "2026-05-07 | ACTION CHANGED | HOLD → REDUCE" in new
    # Original rows preserved
    assert "2024-01-15 | OPENED" in new
    assert "2025-08-10 | THESIS UPDATED" in new


def test_append_history_entry_idempotent() -> None:
    """Appending the same entry twice should leave the file unchanged the second time."""
    entry = HistoryEntry(date=date(2026, 5, 7), event="ACTION CHANGED", detail="HOLD → REDUCE")
    once = append_history_entry(SAMPLE, entry)
    twice = append_history_entry(once, entry)
    assert once == twice


# ---- list_theses + thesis_path --------------------------------------------


def test_list_theses_excludes_template(tmp_path: Path) -> None:
    (tmp_path / "_TEMPLATE.md").write_text("# template")
    (tmp_path / "NVDA.md").write_text("# NVDA")
    (tmp_path / "AAPL.md").write_text("# AAPL")
    (tmp_path / "notes.txt").write_text("not a thesis")
    paths = list_theses(tmp_path)
    names = {p.name for p in paths}
    assert names == {"AAPL.md", "NVDA.md"}


def test_list_theses_empty_when_root_missing(tmp_path: Path) -> None:
    assert list_theses(tmp_path / "nope") == []


def test_thesis_path_uppercases() -> None:
    p = thesis_path(Path("/tmp"), "nvda")
    assert p.name == "NVDA.md"


# ---- YAML-first: parse_kill_conditions ------------------------------------


def test_parse_kill_conditions_from_yaml() -> None:
    """When metadata has kill_conditions as a YAML list, prefer it over the markdown table."""
    kills = parse_kill_conditions(SAMPLE_YAML_STRUCTURED)
    assert len(kills) == 3

    k0 = kills[0]
    assert k0.description == "Revenue growth drops below 5% YoY for two consecutive quarters"
    assert k0.monitoring == "Quarterly 10-Q"
    assert k0.last_checked == date(2026, 5, 16)
    assert k0.status == "clear"

    k2 = kills[2]
    assert k2.description == "Debt/EBITDA exceeds 3.5x"
    assert k2.status == "warning"


def test_parse_kill_conditions_yaml_skips_template_placeholders() -> None:
    """Square-bracket placeholders in YAML trigger should be skipped."""
    content = """## Metadata
```yaml
ticker: X
kill_conditions:
  - trigger: "[TODO: define kill condition]"
    monitor: quarterly
```
"""
    kills = parse_kill_conditions(content)
    assert kills == []


def test_parse_kill_conditions_fallback_when_yaml_absent() -> None:
    """Without kill_conditions in YAML, fall back to markdown table."""
    kills = parse_kill_conditions(SAMPLE)
    assert len(kills) == 2
    assert kills[0].description == "Gross margin < 60%"


# ---- YAML-first: parse_health_components ----------------------------------


def test_parse_health_components_from_yaml() -> None:
    """When metadata has health_components as a YAML list, prefer it over the markdown table."""
    comps, overall = parse_health_components(SAMPLE_YAML_STRUCTURED)
    assert len(comps) == 6
    assert overall == 72

    # Verify we got YAML data, not the fallback table's dummy values
    vs = next(c for c in comps if c.name == "Valuation Safety")
    assert vs.weight == 25
    assert vs.score == 72
    assert "26%" in vs.notes

    bh = next(c for c in comps if c.name == "Business Health")
    assert bh.score == 85
    assert "revenue +12%" in bh.notes


def test_parse_health_components_from_yaml_all_six() -> None:
    """All six standard components present."""
    comps, _ = parse_health_components(SAMPLE_YAML_STRUCTURED)
    names = {c.name for c in comps}
    assert names == {
        "Valuation Safety",
        "Business Health",
        "Insider Alignment",
        "Catalyst Proximity",
        "Thesis Integrity",
        "Risk Environment",
    }


def test_parse_health_components_fallback_when_yaml_absent() -> None:
    """Without health_components in YAML, fall back to markdown table."""
    comps, overall = parse_health_components(SAMPLE)
    assert len(comps) == 6
    assert overall == 78


# ---- YAML-first: parse_metadata_block return types ------------------------


def test_parse_metadata_block_yaml_returns_correct_types() -> None:
    """yaml.safe_load returns native Python types, not strings."""
    raw = parse_metadata_block(SAMPLE_YAML_STRUCTURED)
    assert isinstance(raw["ticker"], str)
    assert isinstance(raw["health_score"], int)
    assert raw["health_score"] == 72
    assert isinstance(raw["cost_basis"], float)
    assert isinstance(raw["shares"], int)
    assert isinstance(raw["kill_conditions"], list)
    assert isinstance(raw["health_components"], list)

    # Nested structures are real dicts
    assert isinstance(raw["kill_conditions"][0], dict)
    assert "trigger" in raw["kill_conditions"][0]


# ---- YAML-first: update_kill_conditions_last_checked ----------------------


def test_update_kill_conditions_last_checked_yaml_path() -> None:
    """When kill_conditions are in YAML, _replace_metadata_block writes them back."""
    when = date(2026, 6, 1)
    new_content = update_kill_conditions_last_checked(SAMPLE_YAML_STRUCTURED, when)
    kills = parse_kill_conditions(new_content)
    assert len(kills) == 3
    assert all(k.last_checked == when for k in kills)

    # Verify the YAML itself was updated, not the legacy table
    assert "2026-06-01" in new_content
    # The legacy table placeholder should still have old date
    assert "YYYY-MM-DD" in new_content


def test_update_kill_conditions_last_checked_preserves_prose() -> None:
    """Kill condition update should not corrupt the thesis title or history."""
    when = date(2026, 6, 1)
    new_content = update_kill_conditions_last_checked(SAMPLE_YAML_STRUCTURED, when)
    assert "grid modernization compounder" in new_content
    assert "2026-05-16 | OPENED" in new_content


# ---- YAML-first: update_health_table --------------------------------------


def test_update_health_table_yaml_path() -> None:
    """When health_components are in YAML, _replace_metadata_block writes them back."""
    new_components = [
        HealthComponent("Valuation Safety", 25, 80),
        HealthComponent("Business Health", 20, 90),
        HealthComponent("Insider Alignment", 10, 65),
        HealthComponent("Catalyst Proximity", 10, 75),
        HealthComponent("Thesis Integrity", 25, 80),
        HealthComponent("Risk Environment", 10, 55),
    ]
    new_content = update_health_table(SAMPLE_YAML_STRUCTURED, new_components, overall=79)
    comps, overall = parse_health_components(new_content)
    assert overall == 79
    assert len(comps) == 6

    vs = next(c for c in comps if c.name == "Valuation Safety")
    assert vs.score == 80

    # The legacy fallback table should be unchanged
    assert "fallback — should be ignored" in new_content


def test_update_health_table_yaml_preserves_prose() -> None:
    """Health table update via YAML path should not corrupt thesis content."""
    new_components = [
        HealthComponent("Valuation Safety", 25, 50),
        HealthComponent("Business Health", 20, 50),
        HealthComponent("Insider Alignment", 10, 50),
        HealthComponent("Catalyst Proximity", 10, 50),
        HealthComponent("Thesis Integrity", 25, 50),
        HealthComponent("Risk Environment", 10, 50),
    ]
    new_content = update_health_table(SAMPLE_YAML_STRUCTURED, new_components, overall=50)
    assert "grid modernization compounder" in new_content
    assert "2026-05-16 | OPENED" in new_content
    # The prose section below the table should be untouched
    assert "## History" in new_content


# ---- YAML round-trip ------------------------------------------------------


def test_yaml_kill_conditions_round_trip() -> None:
    """Update last_checked → verify all fields survive the round-trip."""
    when = date(2026, 7, 1)
    updated = update_kill_conditions_last_checked(SAMPLE_YAML_STRUCTURED, when)
    kills = parse_kill_conditions(updated)

    assert len(kills) == 3
    assert kills[0].description == "Revenue growth drops below 5% YoY for two consecutive quarters"
    assert kills[0].monitoring == "Quarterly 10-Q"
    assert kills[0].status == "clear"
    assert kills[2].status == "warning"


def test_yaml_health_components_round_trip() -> None:
    """Update health table → verify all components survive the round-trip."""
    new_components = [
        HealthComponent("Valuation Safety", 25, 88),
        HealthComponent("Business Health", 20, 90),
        HealthComponent("Insider Alignment", 10, 70),
        HealthComponent("Catalyst Proximity", 10, 80),
        HealthComponent("Thesis Integrity", 25, 85),
        HealthComponent("Risk Environment", 10, 65),
    ]
    updated = update_health_table(SAMPLE_YAML_STRUCTURED, new_components, overall=83)

    # Round-trip: parse the updated content
    meta = parse_metadata_block(updated)
    assert meta["health_score"] == 83
    hc = meta["health_components"]
    assert len(hc) == 6
    assert hc[0]["score"] == 88

    comps, overall = parse_health_components(updated)
    assert overall == 83
    assert len(comps) == 6
    names = {c.name for c in comps}
    assert "Business Health" in names