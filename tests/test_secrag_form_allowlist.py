"""Tests for ai_buffett_zo.secrag.sections — form allowlist + raw-fallback predicate."""

from __future__ import annotations

import pytest

from ai_buffett_zo.secrag import (
    FULL_INDEX_FORMS,
    normalize_form,
    should_full_index,
)


# ---- normalize_form --------------------------------------------------------


def test_normalize_strips_amendment_suffix() -> None:
    assert normalize_form("10-K/A") == "10-K"
    assert normalize_form("10-Q/A") == "10-Q"
    assert normalize_form("S-1/A") == "S-1"


def test_normalize_strips_form_prefix() -> None:
    assert normalize_form("Form 4") == "4"
    assert normalize_form("Form  10-K") == "10-K"


def test_normalize_handles_amendment_and_prefix_together() -> None:
    assert normalize_form("Form 10-K/A") == "10-K"


def test_normalize_strips_whitespace() -> None:
    assert normalize_form("  10-K  ") == "10-K"
    assert normalize_form("\t6-K\n") == "6-K"


def test_normalize_preserves_case() -> None:
    """Canonical SEC form names are mixed case (DEF 14A); normalize must preserve."""
    assert normalize_form("DEF 14A") == "DEF 14A"


def test_normalize_empty_returns_empty() -> None:
    assert normalize_form("") == ""
    assert normalize_form(None) == ""  # type: ignore[arg-type]


# ---- FULL_INDEX_FORMS membership -------------------------------------------


def test_full_index_forms_contains_all_long_structured_filings() -> None:
    """Sanity: the allowlist covers the long, structured filings users index."""
    expected_subset = {
        "10-K", "10-Q",
        "S-1", "S-3", "S-4",
        "20-F", "40-F",
        "DEF 14A",
        "6-K",
        "F-1",
    }
    assert expected_subset.issubset(FULL_INDEX_FORMS)


def test_full_index_forms_excludes_short_filings() -> None:
    """8-K, Form 4 (insider transactions), Form 3/5 take the raw fallback path."""
    short_filings = {"8-K", "4", "3", "5", "Form 4", "13D", "13G"}
    for f in short_filings:
        assert normalize_form(f) not in FULL_INDEX_FORMS, f"{f!r} should not be in full-index allowlist"


# ---- should_full_index -----------------------------------------------------


@pytest.mark.parametrize(
    "form",
    ["10-K", "10-Q", "S-1", "S-3", "S-4", "DEF 14A", "20-F", "40-F", "6-K", "F-1", "F-3", "N-CSR"],
)
def test_should_full_index_true_for_allowlist_forms(form: str) -> None:
    assert should_full_index(form, token_count=100) is True


@pytest.mark.parametrize("form", ["8-K", "4", "3", "5", "13D", "Form 4"])
def test_should_full_index_false_for_short_forms_under_safety_limit(form: str) -> None:
    assert should_full_index(form, token_count=100) is False


@pytest.mark.parametrize("form", ["8-K", "4", "13D"])
def test_should_full_index_true_when_token_count_exceeds_safety_limit(form: str) -> None:
    """A normally-raw form gets full-indexed if it's unusually long
    (e.g., an 8-K with a long exhibit attached)."""
    assert should_full_index(form, token_count=20_000) is True
    assert should_full_index(form, token_count=50_000) is True


def test_should_full_index_safety_limit_is_inclusive_at_threshold() -> None:
    # default raw_token_limit=15_000; > 15000 triggers full index
    assert should_full_index("8-K", token_count=15_000) is False
    assert should_full_index("8-K", token_count=15_001) is True


def test_should_full_index_custom_threshold() -> None:
    assert should_full_index("8-K", token_count=5_000, raw_token_limit=2_000) is True
    assert should_full_index("8-K", token_count=1_500, raw_token_limit=2_000) is False


def test_should_full_index_unknown_form_returns_true() -> None:
    """Unknown form → defensive default: build a tree."""
    assert should_full_index(None, token_count=100) is True


def test_should_full_index_amendment_routes_via_normalize() -> None:
    """`10-K/A` should be allowlisted (it's a 10-K amendment)."""
    assert should_full_index("10-K/A", token_count=100) is True
    assert should_full_index("Form 10-Q/A", token_count=100) is True
