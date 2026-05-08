"""Read and update thesis markdown files.

Design philosophy: be conservative. Locate only well-known regions
(YAML metadata block; named tables under named ## headers); replace
those regions cleanly; leave all prose untouched. If a region looks
unexpected, leave it alone and surface it.

The metadata uses simple `key: value` lines (a YAML subset). We parse
without a YAML dependency to keep the lib's footprint small.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from ai_buffett_zo.theses.types import (
    HealthComponent,
    HistoryEntry,
    KillCondition,
    ThesisMetadata,
)

# ---- File system ----------------------------------------------------------

DEFAULT_THESES_ROOT = Path.home() / "clarion" / "theses"


def list_theses(root: Path = DEFAULT_THESES_ROOT) -> list[Path]:
    """Return all thesis files (excluding the template) sorted by ticker."""
    if not root.exists():
        return []
    return sorted(p for p in root.glob("*.md") if p.name != "_TEMPLATE.md")


def thesis_path(root: Path, ticker: str) -> Path:
    return root / f"{ticker.upper()}.md"


# ---- Metadata block (YAML inside ```yaml ... ``` fence) -------------------

_META_FENCE_RE = re.compile(r"```ya?ml\s*\n(.*?)\n```", re.DOTALL)


def parse_metadata_block(content: str) -> dict[str, str]:
    """Return the raw key/value strings inside the first ```yaml fence."""
    m = _META_FENCE_RE.search(content)
    if m is None:
        return {}
    return _parse_simple_yaml(m.group(1))


def update_metadata_block(content: str, updates: dict[str, object]) -> str:
    """Replace specific key/value pairs in the YAML metadata block.

    Keys not in `updates` are preserved; keys in `updates` are overwritten.
    Returns the new content. If no metadata block is found, returns content
    unchanged.
    """
    m = _META_FENCE_RE.search(content)
    if m is None:
        return content
    block = m.group(1)
    lines = block.splitlines()
    consumed: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        key = _split_key(line)
        if key is None:
            new_lines.append(line)
            continue
        if key in updates:
            new_lines.append(_format_yaml_line(key, updates[key], original=line))
            consumed.add(key)
        else:
            new_lines.append(line)
    # Append any new keys that weren't in the original block
    for k, v in updates.items():
        if k not in consumed:
            new_lines.append(_format_yaml_line(k, v))
    new_block = "\n".join(new_lines)
    return content[: m.start(1)] + new_block + content[m.end(1) :]


def parse_thesis_metadata(content: str) -> ThesisMetadata | None:
    """Parse + coerce the YAML metadata into a typed ThesisMetadata.

    Returns None if required fields are missing. Optional fields are None.
    """
    raw = parse_metadata_block(content)
    if not raw:
        return None
    try:
        return ThesisMetadata(
            ticker=raw["ticker"].upper(),
            company=raw.get("company", ""),
            bucket=raw["bucket"].lower(),  # type: ignore[arg-type]
            status=raw["status"].lower(),  # type: ignore[arg-type]
            opened=date.fromisoformat(raw["opened"]),
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
            return None  # next section, table not found
        if not lines[i].lstrip().startswith("|"):
            continue
        cells = [c.strip().lower() for c in lines[i].strip("|").split("|")]
        if any(e in cells for e in expected):
            # Found header row
            start = i
            end = _table_end(lines, start)
            return (start, end, lines)
    return None


def parse_kill_conditions(content: str) -> list[KillCondition]:
    """Parse the Kill Conditions table from the body."""
    found = find_section_table(
        content,
        section_header="Kill Conditions",
        expected_columns=("kill condition", "condition"),
    )
    if found is None:
        return []
    start, end, lines = found
    out: list[KillCondition] = []
    for i in range(start + 2, end):  # skip header + dashes row
        cells = _row_cells(lines[i])
        if not cells or len(cells) < 3:
            continue
        # Tolerate either 3-col (cond | monitor | last_checked) or 4-col
        # (# | cond | monitor | last_checked) tables.
        if cells[0].isdigit() and len(cells) >= 4:
            cond, monitor, last_checked = cells[1], cells[2], cells[3]
        else:
            cond, monitor, last_checked = cells[0], cells[1], cells[2]
        if not cond or "[" in cond:  # placeholder rows in template
            continue
        out.append(
            KillCondition(
                description=cond,
                monitoring=monitor,
                last_checked=_opt_date(last_checked),
            )
        )
    return out


def parse_health_components(
    content: str,
) -> tuple[list[HealthComponent], int | None]:
    """Parse the Health Scoring table; returns (components, overall_score)."""
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


def update_health_table(
    content: str,
    components: list[HealthComponent],
    overall: int,
) -> str:
    """Replace the body of the Health Scoring table with new scores.

    Preserves the table's surrounding section header and any prose before/
    after. If the table can't be located, returns content unchanged.
    """
    found = find_section_table(
        content,
        section_header="Health Scoring",
        expected_columns=("component",),
    )
    if found is None:
        return content
    start, end, lines = found
    new_table: list[str] = [lines[start], lines[start + 1]]  # header + dashes
    for c in components:
        new_table.append(
            f"| {c.name} | {c.weight}% | {c.score} | {c.notes} |"
        )
    new_table.append(f"| **Overall** | **100%** | **{overall}** | |")
    return "\n".join(lines[:start] + new_table + lines[end:])


def update_kill_conditions_last_checked(content: str, when: date) -> str:
    """Update the 'Last Checked' column on every kill-condition row."""
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
    # Idempotency: skip if the same row already exists in the table
    for i in range(start + 2, end):
        if lines[i].strip() == new_row:
            return content
    # Drop trailing empty placeholder rows like "| | | |"
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
    """Return one past the last data row of the table starting at `start`."""
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


def _parse_simple_yaml(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()  # strip comments
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip()
        # Skip nested structures (lists / dicts) — not used in our flat metadata
        if v.startswith("[") or v.startswith("{") or v == "" and k == "":
            continue
        out[k] = v
    return out


def _split_key(line: str) -> str | None:
    """Return the key from `key: value` lines, or None for non-key lines."""
    stripped = line.split("#", 1)[0].rstrip()
    if ":" not in stripped:
        return None
    head = stripped.split(":", 1)[0]
    # YAML key must not start with whitespace at this level
    if head != head.lstrip():
        return None
    return head.strip() or None


def _format_yaml_line(key: str, value: object, original: str | None = None) -> str:
    """Emit `key: value`, preserving any inline comment from `original`."""
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
        return int(float(value))  # tolerates "55.0"
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
