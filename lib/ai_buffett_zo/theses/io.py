"""Read and update thesis markdown files.

Design philosophy: be conservative. Locate only well-known regions
(YAML metadata block; named tables under named ## headers); replace
those regions cleanly; leave all prose untouched. If a region looks
unexpected, leave it alone and surface it.

The metadata block is full YAML (parsed with PyYAML). Nested structures
(kill_conditions, health_components, position, valuation) are read from
and written back to the YAML fence. Flat keys (ticker, health_score, etc.)
are still updated line-by-line to preserve inline comments.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date
from pathlib import Path

import yaml

from ai_buffett_zo._paths import clarion_home
from ai_buffett_zo.theses.types import (
    HealthComponent,
    HealthSnapshot,
    HistoryEntry,
    KillCondition,
    ThesisMetadata,
)

# ---- File system ----------------------------------------------------------

DEFAULT_THESES_ROOT = clarion_home() / "theses"


def list_theses(root: Path = DEFAULT_THESES_ROOT) -> list[Path]:
    """Return all thesis files (excluding the template) sorted by ticker."""
    if not root.exists():
        return []
    return sorted(p for p in root.glob("*.md") if p.name != "_TEMPLATE.md")


def thesis_path(root: Path, ticker: str) -> Path:
    return root / f"{ticker.upper()}.md"


# ---- Metadata block (YAML inside ```yaml ... ``` fence) -------------------

_META_FENCE_RE = re.compile(r"```ya?ml\s*\n(.*?)\n```", re.DOTALL)

# Keys that contain nested structures (not flat scalar values).
_NESTED_KEYS = frozenset({
    "kill_conditions", "health_components", "position", "valuation",
})


def parse_metadata_block(content: str) -> dict:
    """Return the parsed YAML dict from inside the first ```yaml fence.

    Returns a dict that may contain nested structures (kill_conditions,
    health_components, position, valuation) alongside flat scalar values.
    Returns {} if no metadata block is found.
    """
    m = _META_FENCE_RE.search(content)
    if m is None:
        return {}
    data = yaml.safe_load(m.group(1))
    if not isinstance(data, dict):
        return {}
    return data


def update_metadata_block(content: str, updates: dict[str, object]) -> str:
    """Replace specific flat key/value pairs in the YAML metadata block.

    Keys not in `updates` are preserved; keys in `updates` are overwritten.
    For nested structures (kill_conditions, health_components, position,
    valuation), use the specialized update functions instead — this function
    only handles flat scalar keys.

    Returns the new content. If no metadata block is found, returns content
    unchanged.
    """
    m = _META_FENCE_RE.search(content)
    if m is None:
        return content
    block = m.group(1)
    accepted = {k: v for k, v in updates.items() if k not in _NESTED_KEYS}
    if not accepted:
        return content
    lines = block.splitlines()
    consumed: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        key = _split_key(line)
        if key is None:
            new_lines.append(line)
            continue
        if key in accepted:
            new_lines.append(_format_yaml_line(key, accepted[key], original=line))
            consumed.add(key)
        else:
            new_lines.append(line)
    for k, v in accepted.items():
        if k not in consumed:
            new_lines.append(_format_yaml_line(k, v))
    new_block = "\n".join(new_lines)
    return content[: m.start(1)] + new_block + content[m.end(1):]


def _replace_metadata_block(content: str, data: dict) -> str:
    """Replace the entire YAML block with a fresh dump of `data`.

    Preserves the ```yaml fence and surrounding markdown.
    """
    m = _META_FENCE_RE.search(content)
    if m is None:
        return content
    new_yaml = yaml.dump(
        data,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    ).rstrip("\n")
    return content[: m.start(1)] + new_yaml + content[m.end(1):]


def parse_thesis_metadata(content: str) -> ThesisMetadata | None:
    """Parse + coerce the YAML metadata into a typed ThesisMetadata.

    Returns None if required fields are missing. Optional fields are None.
    """
    raw = parse_metadata_block(content)
    if not raw:
        return None
    try:
        return ThesisMetadata(
            ticker=str(raw["ticker"]).upper(),
            company=str(raw.get("company", "")),
            bucket=str(raw["bucket"]).lower(),  # type: ignore[arg-type]
            status=str(raw["status"]).lower(),  # type: ignore[arg-type]
            opened=date.fromisoformat(str(raw["opened"])),
            last_reviewed=_opt_date(raw.get("last_reviewed")),
            health_score=_opt_int(raw.get("health_score")),
            cost_basis=_opt_float(raw.get("cost_basis")),
            shares=int(raw.get("shares") or 0),
            portfolio_weight=_opt_float(raw.get("portfolio_weight")),
        )
    except (KeyError, ValueError):
        return None


# ---- Tables under section headers -----------------------------------------


def find_section_table(
    content: str,
    *,
    section_header: str,
    expected_columns: Iterable[str],
) -> tuple[int, int, list[str]] | None:
    """Locate a markdown table under a section header.

    Returns (table_start, table_end, all_lines) — table_start is the index of
    the header row, table_end is one past the last data row. all_lines is the
    full content split. None if not found.
    """
    lines = content.splitlines()
    sect_idx = _find_section(lines, section_header)
    if sect_idx is None:
        return None
    expected = [c.lower() for c in expected_columns]
    for i in range(sect_idx + 1, len(lines)):
        if lines[i].startswith("## "):
            return None
        if not lines[i].lstrip().startswith("|"):
            continue
        cells = [c.strip().lower() for c in lines[i].strip("|").split("|")]
        if any(e in cells for e in expected):
            start = i
            end = _table_end(lines, start)
            return (start, end, lines)
    return None


# ---- Kill conditions ------------------------------------------------------


def parse_kill_conditions(content: str) -> list[KillCondition]:
    """Parse kill conditions — YAML-first, fall back to markdown table."""
    meta = parse_metadata_block(content)
    yaml_kcs = meta.get("kill_conditions")
    if isinstance(yaml_kcs, list) and yaml_kcs:
        return _kill_conditions_from_yaml(yaml_kcs)
    return _parse_kill_conditions_from_table(content)


def _kill_conditions_from_yaml(raw: list[dict]) -> list[KillCondition]:
    out: list[KillCondition] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        desc = item.get("trigger", "") or item.get("description", "")
        if not desc or "[" in str(desc):
            continue
        out.append(KillCondition(
            description=str(desc),
            monitoring=str(item.get("monitor", "")),
            last_checked=_opt_date(item.get("last_checked")),
            status=item.get("status", "clear"),  # type: ignore[arg-type]
        ))
    return out


def _parse_kill_conditions_from_table(content: str) -> list[KillCondition]:
    """Parse the Kill Conditions markdown table (legacy fallback)."""
    found = find_section_table(
        content,
        section_header="Kill Conditions",
        expected_columns=("kill condition", "condition"),
    )
    if found is None:
        return []
    start, end, lines = found
    out: list[KillCondition] = []
    for i in range(start + 2, end):
        cells = _row_cells(lines[i])
        if not cells or len(cells) < 3:
            continue
        if cells[0].isdigit() and len(cells) >= 4:
            cond, monitor, last_checked = cells[1], cells[2], cells[3]
        else:
            cond, monitor, last_checked = cells[0], cells[1], cells[2]
        if not cond or "[" in cond:
            continue
        out.append(KillCondition(
            description=cond,
            monitoring=monitor,
            last_checked=_opt_date(last_checked),
        ))
    return out


# ---- Health components ----------------------------------------------------


def parse_health_components(
    content: str,
) -> tuple[list[HealthComponent], int | None]:
    """Parse health components — YAML-first, fall back to markdown table."""
    meta = parse_metadata_block(content)
    yaml_hc = meta.get("health_components")
    if isinstance(yaml_hc, (list, dict)) and yaml_hc:
        return _health_components_from_yaml(yaml_hc, meta)
    return _parse_health_components_from_table(content)


def _health_components_from_yaml(
    raw: list[dict] | dict,
    meta: dict,
) -> tuple[list[HealthComponent], int | None]:
    components: list[HealthComponent] = []

    items: list[tuple[str, dict]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and "name" in item:
                items.append((str(item["name"]), item))
    elif isinstance(raw, dict):
        for slug, item in raw.items():
            if isinstance(item, dict):
                items.append((slug.replace("_", " ").title(), item))

    for name, item in items:
        if not name or "[" in name:
            continue
        components.append(HealthComponent(
            name=name,
            weight=int(item.get("weight", 0)),
            score=int(item.get("score", 0)),
            notes=str(item.get("notes", "") or item.get("note", "")),
        ))
    overall = _opt_int(meta.get("health_score"))
    return components, overall


def _parse_health_components_from_table(
    content: str,
) -> tuple[list[HealthComponent], int | None]:
    """Parse the Health Scoring markdown table (legacy fallback)."""
    found = find_section_table(
        content,
        section_header="Health Scoring",
        expected_columns=("component",),
    )
    if found is None:
        return [], None
    start, end, lines = found
    components: list[HealthComponent] = []
    overall: int | None = None
    for i in range(start + 2, end):
        cells = _row_cells(lines[i])
        if not cells or len(cells) < 3:
            continue
        name = cells[0].replace("**", "").strip()
        if not name or "[" in name:
            continue
        weight_s = cells[1].replace("**", "").replace("%", "").strip()
        score_s = cells[2].replace("**", "").strip()
        weight = _opt_int(weight_s)
        score = _opt_int(score_s)
        if name.lower() == "overall":
            if score is not None:
                overall = score
            continue
        if weight is None or score is None:
            continue
        notes = cells[3] if len(cells) >= 4 else ""
        components.append(
            HealthComponent(name=name, weight=weight, score=score, notes=notes)
        )
    return components, overall


# ---- Update functions -----------------------------------------------------


def update_health_table(
    content: str,
    components: list[HealthComponent],
    overall: int,
) -> str:
    """Replace health component scores — YAML if present, else markdown table."""
    meta = parse_metadata_block(content)
    if "health_components" in meta:
        new_components: list[dict] = []
        for c in components:
            new_components.append({
                "name": c.name,
                "weight": c.weight,
                "score": c.score,
                "notes": c.notes,
            })
        meta["health_components"] = new_components
        meta["health_score"] = overall
        return _replace_metadata_block(content, meta)

    # Legacy markdown table path
    found = find_section_table(
        content,
        section_header="Health Scoring",
        expected_columns=("component",),
    )
    if found is None:
        return content
    start, end, lines = found
    new_table: list[str] = [lines[start], lines[start + 1]]
    for c in components:
        new_table.append(f"| {c.name} | {c.weight}% | {c.score} | {c.notes} |")
    new_table.append(f"| **Overall** | **100%** | **{overall}** | |")
    return "\n".join(lines[:start] + new_table + lines[end:])


def update_kill_conditions_last_checked(content: str, when: date) -> str:
    """Update 'last_checked' on every kill condition — YAML if present, else table."""
    meta = parse_metadata_block(content)
    yaml_kcs = meta.get("kill_conditions")
    if isinstance(yaml_kcs, list):
        for kc in yaml_kcs:
            if isinstance(kc, dict):
                kc["last_checked"] = when.isoformat()
        return _replace_metadata_block(content, meta)

    # Legacy markdown table path
    found = find_section_table(
        content,
        section_header="Kill Conditions",
        expected_columns=("kill condition", "condition"),
    )
    if found is None:
        return content
    start, end, lines = found
    iso = when.isoformat()
    new_lines = lines.copy()
    for i in range(start + 2, end):
        cells = _row_cells(new_lines[i])
        if not cells or len(cells) < 3:
            continue
        if cells[0].isdigit() and len(cells) >= 4:
            cells[3] = iso
        else:
            cells[2] = iso
        new_lines[i] = "| " + " | ".join(cells) + " |"
    return "\n".join(new_lines)


def append_history_entry(content: str, entry: HistoryEntry) -> str:
    """Append a row to the History table. Idempotent if the row already exists."""
    found = find_section_table(
        content,
        section_header="History",
        expected_columns=("date",),
    )
    if found is None:
        return content
    start, end, lines = found
    iso = entry.date.isoformat()
    new_row = f"| {iso} | {entry.event} | {entry.detail} |"
    for i in range(start + 2, end):
        if lines[i].strip() == new_row:
            return content
    insert_at = end
    if end > start + 2 and _row_cells(lines[end - 1]) == ["", "", ""]:
        insert_at = end - 1
    new_lines = lines[:insert_at] + [new_row] + lines[insert_at:]
    return "\n".join(new_lines)


# ---- Internal helpers -----------------------------------------------------


def _find_section(lines: list[str], header: str) -> int | None:
    needle = header.lower()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("##"):
            txt = line.lstrip("#").strip().lower()
            if txt == needle or txt.startswith(needle):
                return i
    return None


def _table_end(lines: list[str], start: int) -> int:
    i = start + 1
    while i < len(lines) and lines[i].lstrip().startswith("|"):
        i += 1
    return i


def _row_cells(line: str) -> list[str]:
    s = line.strip()
    if not s.startswith("|"):
        return []
    inner = s.strip("|")
    return [c.strip() for c in inner.split("|")]


def _split_key(line: str) -> str | None:
    stripped = line.split("#", 1)[0].rstrip()
    if ":" not in stripped:
        return None
    head = stripped.split(":", 1)[0]
    if head != head.lstrip():
        return None
    return head.strip() or None


def _format_yaml_line(key: str, value: object, original: str | None = None) -> str:
    if isinstance(value, date):
        v = value.isoformat()
    elif value is None:
        v = ""
    elif isinstance(value, bool):
        v = "true" if value else "false"
    else:
        v = str(value)
    if original and "#" in original:
        comment = "  #" + original.split("#", 1)[1]
        return f"{key}: {v}{comment}"
    return f"{key}: {v}"


def _opt_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _opt_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_date(value: object) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None
