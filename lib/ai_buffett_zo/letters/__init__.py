"""Annual investor letter — types, I/O, and section composition."""

from ai_buffett_zo.letters.compose import (
    render_finalization,
    render_quarterly_section,
)
from ai_buffett_zo.letters.io import (
    DEFAULT_LETTERS_ROOT,
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

__all__ = [
    "DEFAULT_LETTERS_ROOT",
    "QUARTER_LABELS",
    "current_quarter",
    "ensure_letter",
    "is_finalized",
    "is_quarter_populated",
    "letter_path",
    "list_letters",
    "render_finalization",
    "render_quarterly_section",
    "render_skeleton",
    "replace_full_year_summary",
    "replace_quarter",
    "replace_year_in_context",
]
