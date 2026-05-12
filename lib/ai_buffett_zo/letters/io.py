"""Read and update annual investor-letter files.

The letter is a per-year markdown file at ~/clarion/letters/{YEAR}-letter.md
following the format spec from docs/PRINCIPLES.md (Principle 10) and the
AWB LIVING-LETTER-FORMAT.md.

Append-only philosophy: never edit past quarters retroactively. The lib's
update functions check whether a quarter has been populated; if so, they
refuse to overwrite without explicit force. Hindsight commentary belongs
in NEW sections (in brackets), not as edits to old ones.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from ai_buffett_zo._paths import clarion_home

DEFAULT_LETTERS_ROOT = clarion_home() / "letters"

# Markers that distinguish a populated quarter from a placeholder.
_POPULATED_MARKERS = (
    "### Regime & Environment",
    "### Portfolio Snapshot",
    "### What We Did",
    "### Thesis Health",
    "### What We Learned",
)

QUARTER_LABELS: dict[int, str] = {
    1: "Q1: January — March",
    2: "Q2: April — June",
    3: "Q3: July — September",
    4: "Q4: October — December",
}


def letter_path(root: Path, year: int) -> Path:
    return root / f"{year}-letter.md"


def list_letters(root: Path = DEFAULT_LETTERS_ROOT) -> list[Path]:
    """Letter files sorted oldest-first by year in the filename."""
    if not root.exists():
        return []
    return sorted(root.glob("*-letter.md"))


def current_quarter(asof: date | None = None) -> int:
    """Standard calendar quarter (1-4) from a date."""
    asof = asof or date.today()
    return (asof.month - 1) // 3 + 1


# ---- Skeleton creation -----------------------------------------------------


def render_skeleton(year: int) -> str:
    """Initial empty letter for `year` with placeholders for all four quarters
    and the year-end sections."""
    parts = [
        f"# Clarion Intelligence System — {year} Investor Letter",
        "",
        "> [Year-end only: a single sentence that captures the year's most important lesson.]",
        "",
        "---",
        "",
        "## Year in Context",
        "",
        "[Year-end only: 2-3 paragraphs setting the scene. What was the macro environment? "
        "What regime(s) did the system operate in? What was the dominant narrative — and did "
        "the system agree with it? Written in hindsight with the benefit of the full year's perspective.]",
        "",
        "---",
        "",
    ]
    for q in (1, 2, 3, 4):
        parts.extend([
            f"## {QUARTER_LABELS[q]}",
            "",
            "[To be populated.]",
            "",
            "---",
            "",
        ])
    parts.extend([
        "## Full Year Summary",
        "",
        "[To be written at year-end finalization.]",
        "",
    ])
    return "\n".join(parts).rstrip() + "\n"


def ensure_letter(root: Path, year: int) -> Path:
    """Create the letter skeleton if missing. Returns the path."""
    root.mkdir(parents=True, exist_ok=True)
    p = letter_path(root, year)
    if not p.exists():
        p.write_text(render_skeleton(year))
    return p


# ---- Quarter populated check ----------------------------------------------


_QUARTER_HEADER_RE = re.compile(r"^## (Q[1-4]):", re.MULTILINE)
_FULL_YEAR_HEADER_RE = re.compile(r"^## Full Year Summary", re.MULTILINE)
_YEAR_CONTEXT_HEADER_RE = re.compile(r"^## Year in Context", re.MULTILINE)


def _quarter_section_bounds(content: str, quarter: int) -> tuple[int, int] | None:
    """Return (start, end) line indices for the Q{quarter} section.

    `start` is the line index of the `## Q{N}:` header. `end` is the line index
    of the next `## ` header (Full Year Summary or next quarter). None if the
    quarter header isn't found.
    """
    needle = f"## Q{quarter}:"
    lines = content.splitlines()
    start: int | None = None
    for i, line in enumerate(lines):
        if line.startswith(needle):
            start = i
            break
    if start is None:
        return None
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            return (start, j)
    return (start, len(lines))


def is_quarter_populated(content: str, quarter: int) -> bool:
    """A quarter is populated if its section contains any structural marker
    (### Regime & Environment, ### What We Did, etc.). The placeholder
    `[To be populated.]` does not count."""
    bounds = _quarter_section_bounds(content, quarter)
    if bounds is None:
        return False
    start, end = bounds
    section = "\n".join(content.splitlines()[start:end])
    return any(marker in section for marker in _POPULATED_MARKERS)


def is_finalized(content: str) -> bool:
    """The letter is finalized if Full Year Summary contains structural content."""
    m = _FULL_YEAR_HEADER_RE.search(content)
    if m is None:
        return False
    summary_block = content[m.start():]
    return any(
        marker in summary_block
        for marker in (
            "### Performance",
            "### By Bucket",
            "### Mistakes & Lessons",
            "### Theses: Final Scorecard",
            "### Looking Ahead",
        )
    )


# ---- Update operations -----------------------------------------------------


def replace_quarter(content: str, quarter: int, new_section: str) -> str:
    """Replace the Q{quarter} section's body (everything after the header line
    up to the next ## section).

    The new_section text should NOT include the `## Q{N}:` header line — that's
    preserved from the original document.
    """
    bounds = _quarter_section_bounds(content, quarter)
    if bounds is None:
        raise ValueError(f"Q{quarter} header not found in letter")
    start, end = bounds
    lines = content.splitlines()
    header = lines[start]
    # Find the trailing `---` separator before the next section to preserve it
    # (ours is always at end - 2 if present).
    body_lines = new_section.rstrip().splitlines()
    rebuilt = [header, ""] + body_lines + ["", "---", ""]
    return "\n".join(lines[:start] + rebuilt + lines[end:]).rstrip() + "\n"


def replace_year_in_context(content: str, new_section: str) -> str:
    """Replace the Year in Context section body (header preserved)."""
    m = _YEAR_CONTEXT_HEADER_RE.search(content)
    if m is None:
        raise ValueError("Year in Context header not found")
    lines = content.splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.startswith("## Year in Context")
    )
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    body = new_section.rstrip().splitlines()
    rebuilt = [lines[start], ""] + body + ["", "---", ""]
    return "\n".join(lines[:start] + rebuilt + lines[end:]).rstrip() + "\n"


def replace_full_year_summary(content: str, new_section: str) -> str:
    """Replace the Full Year Summary section body (header preserved)."""
    m = _FULL_YEAR_HEADER_RE.search(content)
    if m is None:
        raise ValueError("Full Year Summary header not found")
    lines = content.splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.startswith("## Full Year Summary")
    )
    body = new_section.rstrip().splitlines()
    rebuilt = [lines[start], ""] + body
    return "\n".join(lines[:start] + rebuilt).rstrip() + "\n"
