"""Tests for ai_buffett_zo.observability.timing."""

from __future__ import annotations

import pytest

from ai_buffett_zo.observability import Timing


def test_stage_records_duration() -> None:
    t = Timing()
    with t.stage("work"):
        pass
    assert len(t.stages) == 1
    name, secs = t.stages[0]
    assert name == "work"
    assert secs >= 0.0


def test_stages_preserve_order() -> None:
    t = Timing()
    with t.stage("first"):
        pass
    with t.stage("second"):
        pass
    with t.stage("third"):
        pass
    assert [name for name, _ in t.stages] == ["first", "second", "third"]


def test_stage_records_even_on_exception() -> None:
    """A failing stage still shows up in the summary — that's the point."""
    t = Timing()
    with pytest.raises(ValueError):
        with t.stage("boom"):
            raise ValueError("kaboom")
    assert [name for name, _ in t.stages] == ["boom"]


def test_record_external_duration() -> None:
    t = Timing()
    t.record("subprocess wall time", 12.5)
    assert t.as_dict()["subprocess wall time"] == 12.5


def test_total_is_monotonic_nonnegative() -> None:
    t = Timing()
    assert t.total() >= 0.0


def test_summary_format() -> None:
    t = Timing()
    t.record("yfinance snapshot", 1.2)
    t.record("regime check", 0.8)
    summary = t.summary()
    lines = summary.splitlines()
    assert lines[0] == "Timing:"
    assert lines[1] == "- yfinance snapshot: 1.2s"
    assert lines[2] == "- regime check: 0.8s"
    assert lines[-1].startswith("Total: ")
    assert lines[-1].endswith("s")


def test_summary_custom_title() -> None:
    t = Timing()
    t.record("fetch", 2.0)
    summary = t.summary(title="IBM 10-K indexing")
    assert summary.startswith("IBM 10-K indexing:")


def test_summary_empty_has_title_and_total() -> None:
    t = Timing()
    summary = t.summary()
    lines = summary.splitlines()
    assert lines[0] == "Timing:"
    assert lines[1].startswith("Total: ")


def test_as_dict_last_write_wins() -> None:
    """Duplicate stage names collapse — last duration wins in the dict view."""
    t = Timing()
    t.record("fetch", 1.0)
    t.record("fetch", 3.0)
    assert t.as_dict()["fetch"] == 3.0
    # But stages list keeps both for the ordered summary
    assert len(t.stages) == 2
