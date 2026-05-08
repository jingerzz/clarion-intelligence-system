"""Tests for ai_buffett_zo.letters.io."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ai_buffett_zo.letters import (
    QUARTER_LABELS,
    current_quarter,
    ensure_letter,
    is_finalized,
    is_quarter_populated,
    letter_path,
    list_letters,
    render_skeleton,
    replace_full_year_summary,
    replace_quarter,
    replace_year_in_context,
)


# ---- current_quarter -------------------------------------------------------


def test_current_quarter_buckets() -> None:
    assert current_quarter(date(2026, 1, 1)) == 1
    assert current_quarter(date(2026, 3, 31)) == 1
    assert current_quarter(date(2026, 4, 1)) == 2
    assert current_quarter(date(2026, 6, 30)) == 2
    assert current_quarter(date(2026, 7, 1)) == 3
    assert current_quarter(date(2026, 9, 30)) == 3
    assert current_quarter(date(2026, 10, 1)) == 4
    assert current_quarter(date(2026, 12, 31)) == 4


# ---- letter_path / list_letters --------------------------------------------


def test_letter_path_format() -> None:
    p = letter_path(Path("/tmp"), 2026)
    assert p.name == "2026-letter.md"


def test_list_letters_sorted_and_filtered(tmp_path: Path) -> None:
    (tmp_path / "2024-letter.md").write_text("x")
    (tmp_path / "2026-letter.md").write_text("x")
    (tmp_path / "2025-letter.md").write_text("x")
    (tmp_path / "notes.md").write_text("not a letter")
    files = list_letters(tmp_path)
    assert [f.name for f in files] == ["2024-letter.md", "2025-letter.md", "2026-letter.md"]


def test_list_letters_empty_when_root_missing(tmp_path: Path) -> None:
    assert list_letters(tmp_path / "nope") == []


# ---- render_skeleton -------------------------------------------------------


def test_render_skeleton_has_all_sections() -> None:
    text = render_skeleton(2026)
    assert "Clarion Intelligence System — 2026 Investor Letter" in text
    assert "## Year in Context" in text
    for q in (1, 2, 3, 4):
        assert f"## {QUARTER_LABELS[q]}" in text
    assert "## Full Year Summary" in text
    assert "[To be populated.]" in text


# ---- ensure_letter --------------------------------------------------------


def test_ensure_letter_creates_when_missing(tmp_path: Path) -> None:
    path = ensure_letter(tmp_path, 2026)
    assert path.exists()
    assert "2026 Investor Letter" in path.read_text()


def test_ensure_letter_idempotent_when_present(tmp_path: Path) -> None:
    p = ensure_letter(tmp_path, 2026)
    custom = "# Already-customized letter\n\n## Q1: January — March\n\n### What We Did\n\nstuff happened\n"
    p.write_text(custom)

    again = ensure_letter(tmp_path, 2026)
    assert again == p
    assert again.read_text() == custom  # unchanged


# ---- is_quarter_populated -------------------------------------------------


def test_is_quarter_populated_skeleton_returns_false(tmp_path: Path) -> None:
    text = render_skeleton(2026)
    for q in (1, 2, 3, 4):
        assert is_quarter_populated(text, q) is False


def test_is_quarter_populated_with_structural_content_returns_true() -> None:
    text = """
## Q2: April — June

### What We Did

We did stuff.

---
"""
    assert is_quarter_populated(text, 2) is True


def test_is_quarter_populated_other_quarters_unaffected() -> None:
    text = render_skeleton(2026).replace(
        "## Q2: April — June\n\n[To be populated.]",
        "## Q2: April — June\n\n### What We Did\n\nthings\n",
    )
    assert is_quarter_populated(text, 1) is False
    assert is_quarter_populated(text, 2) is True
    assert is_quarter_populated(text, 3) is False


def test_is_quarter_populated_missing_quarter_returns_false() -> None:
    """Letter without the requested quarter section returns False (not error)."""
    assert is_quarter_populated("# Just a title", 2) is False


# ---- is_finalized ----------------------------------------------------------


def test_is_finalized_skeleton_returns_false() -> None:
    assert is_finalized(render_skeleton(2026)) is False


def test_is_finalized_with_summary_content_returns_true() -> None:
    text = render_skeleton(2026).replace(
        "## Full Year Summary\n\n[To be written at year-end finalization.]",
        "## Full Year Summary\n\n### Performance\n\n| Metric |\n|---|\n| Total Return |\n",
    )
    assert is_finalized(text) is True


# ---- replace_quarter -------------------------------------------------------


def test_replace_quarter_writes_new_section() -> None:
    text = render_skeleton(2026)
    new_content = replace_quarter(text, 2, "**Updated: 2026-05-07**\n\n### Regime & Environment\n- foo")
    assert "## Q2: April — June" in new_content
    assert "Updated: 2026-05-07" in new_content
    assert "### Regime & Environment" in new_content
    assert is_quarter_populated(new_content, 2) is True
    # Other quarters still placeholder
    assert is_quarter_populated(new_content, 1) is False
    assert is_quarter_populated(new_content, 3) is False


def test_replace_quarter_preserves_year_in_context_and_summary() -> None:
    text = render_skeleton(2026)
    new = replace_quarter(text, 2, "### What We Did\n\nstuff")
    assert "## Year in Context" in new
    assert "## Full Year Summary" in new


# ---- replace_year_in_context ----------------------------------------------


def test_replace_year_in_context_writes_new_section() -> None:
    text = render_skeleton(2026)
    new = replace_year_in_context(text, "2026 was a year of transitions.")
    assert "2026 was a year of transitions." in new
    assert "## Year in Context" in new
    # Quarters preserved
    for q in (1, 2, 3, 4):
        assert f"## {QUARTER_LABELS[q]}" in new


# ---- replace_full_year_summary --------------------------------------------


def test_replace_full_year_summary_writes_new_section() -> None:
    text = render_skeleton(2026)
    new = replace_full_year_summary(text, "*Finalized: 2027-01-15*\n\n### Performance\n\nx")
    assert "*Finalized: 2027-01-15*" in new
    assert is_finalized(new) is True
