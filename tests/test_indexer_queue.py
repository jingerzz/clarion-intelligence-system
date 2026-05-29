"""Tests for ai_buffett_zo.indexer.queue."""

from __future__ import annotations

import json
import time
from pathlib import Path

from ai_buffett_zo.indexer import (
    IndexRequest,
    claim,
    default_priority,
    enqueue,
    list_pending,
    mark_done,
    mark_failed,
)
from ai_buffett_zo.indexer.queue import (
    PRIORITY_P1,
    PRIORITY_P2,
    PRIORITY_P3,
    PRIORITY_P4,
)


def test_index_request_new_uppercases_and_sets_id() -> None:
    r = IndexRequest.new("nvda", "10-K")
    assert r.ticker == "NVDA"
    assert r.form == "10-K"
    assert len(r.id) == 12
    assert r.requested_at  # ISO string
    assert r.model is None


def test_enqueue_writes_pending_file(tmp_path: Path) -> None:
    r = IndexRequest.new("NVDA", "10-K")
    path = enqueue(r, root=tmp_path)
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["ticker"] == "NVDA"
    assert data["id"] == r.id


def test_list_pending_empty_dir(tmp_path: Path) -> None:
    assert list_pending(tmp_path / "nope") == []
    assert list_pending(tmp_path) == []


def test_list_pending_returns_in_mtime_order(tmp_path: Path) -> None:
    a = IndexRequest.new("AAA")
    b = IndexRequest.new("BBB")
    c = IndexRequest.new("CCC")
    enqueue(a, root=tmp_path)
    time.sleep(0.01)
    enqueue(b, root=tmp_path)
    time.sleep(0.01)
    enqueue(c, root=tmp_path)
    pending = list_pending(tmp_path)
    assert [p.ticker for p in pending] == ["AAA", "BBB", "CCC"]


def test_list_pending_skips_processing_dirs(tmp_path: Path) -> None:
    """Files in .processing/ / .done/ / .failed/ should not be listed as pending."""
    enqueue(IndexRequest.new("AAA"), root=tmp_path)
    (tmp_path / ".processing").mkdir()
    (tmp_path / ".processing" / "old.json").write_text("{}")
    (tmp_path / ".done").mkdir()
    (tmp_path / ".done" / "x.json").write_text("{}")
    pending = list_pending(tmp_path)
    assert len(pending) == 1
    assert pending[0].ticker == "AAA"


def test_list_pending_skips_malformed(tmp_path: Path) -> None:
    enqueue(IndexRequest.new("AAA"), root=tmp_path)
    (tmp_path / "bad.json").write_text("not valid json")
    pending = list_pending(tmp_path)
    assert len(pending) == 1
    assert pending[0].ticker == "AAA"


def test_claim_moves_to_processing(tmp_path: Path) -> None:
    r = IndexRequest.new("NVDA")
    enqueue(r, root=tmp_path)

    new_path = claim(r.id, root=tmp_path)
    assert new_path is not None
    assert new_path == tmp_path / ".processing" / f"{r.id}.json"
    assert new_path.exists()
    assert not (tmp_path / f"{r.id}.json").exists()


def test_claim_missing_returns_none(tmp_path: Path) -> None:
    assert claim("nonexistent", root=tmp_path) is None


def test_mark_done_moves_to_done(tmp_path: Path) -> None:
    r = IndexRequest.new("NVDA")
    enqueue(r, root=tmp_path)
    claim(r.id, root=tmp_path)

    mark_done(r.id, root=tmp_path)

    assert (tmp_path / ".done" / f"{r.id}.json").exists()
    assert not (tmp_path / ".processing" / f"{r.id}.json").exists()


def test_mark_done_idempotent_when_missing(tmp_path: Path) -> None:
    # Should not raise
    mark_done("never-claimed", root=tmp_path)


def test_mark_failed_writes_error_into_body(tmp_path: Path) -> None:
    r = IndexRequest.new("NVDA")
    enqueue(r, root=tmp_path)
    claim(r.id, root=tmp_path)

    mark_failed(r.id, "EDGAR returned 503", root=tmp_path)

    failed_file = tmp_path / ".failed" / f"{r.id}.json"
    assert failed_file.exists()
    body = json.loads(failed_file.read_text())
    assert body["error"] == "EDGAR returned 503"
    assert body["failed_at"]
    assert body["ticker"] == "NVDA"   # original fields preserved


def test_mark_failed_idempotent_when_missing(tmp_path: Path) -> None:
    mark_failed("never-claimed", "x", root=tmp_path)


# ---- priority scheduling (issue #39) ---------------------------------------


def test_default_priority_tiers() -> None:
    assert default_priority("10-K") == PRIORITY_P1
    assert default_priority("10-Q") == PRIORITY_P1
    assert default_priority("20-F") == PRIORITY_P1
    assert default_priority("DEF 14A") == PRIORITY_P2
    assert default_priority("8-K") == PRIORITY_P2
    assert default_priority("4") == PRIORITY_P3
    assert default_priority("SC 13G") == PRIORITY_P4  # unrecognized → last


def test_default_priority_normalizes_amendment_and_case() -> None:
    assert default_priority("10-k") == PRIORITY_P1
    assert default_priority("10-K/A") == PRIORITY_P1
    assert default_priority("Form 4") == PRIORITY_P3


def test_index_request_new_derives_priority_from_form() -> None:
    assert IndexRequest.new("NVDA", "10-K").priority == PRIORITY_P1
    assert IndexRequest.new("NVDA", "8-K").priority == PRIORITY_P2
    assert IndexRequest.new("NVDA", "4").priority == PRIORITY_P3


def test_index_request_new_explicit_priority_overrides_form() -> None:
    r = IndexRequest.new("NVDA", "8-K", priority=PRIORITY_P1)
    assert r.priority == PRIORITY_P1


def test_enqueue_persists_priority(tmp_path: Path) -> None:
    r = IndexRequest.new("NVDA", "8-K")
    path = enqueue(r, root=tmp_path)
    assert json.loads(path.read_text())["priority"] == PRIORITY_P2


def test_list_pending_high_priority_jumps_ahead_of_older_low_priority(tmp_path: Path) -> None:
    """A 10-K enqueued last still drains before earlier low-signal filings."""
    enqueue(IndexRequest.new("AAA", "4"), root=tmp_path)       # P3, oldest
    time.sleep(0.01)
    enqueue(IndexRequest.new("BBB", "8-K"), root=tmp_path)     # P2
    time.sleep(0.01)
    enqueue(IndexRequest.new("CCC", "10-K"), root=tmp_path)    # P1, newest
    pending = list_pending(tmp_path)
    assert [p.ticker for p in pending] == ["CCC", "BBB", "AAA"]


def test_list_pending_fifo_within_a_priority_tier(tmp_path: Path) -> None:
    enqueue(IndexRequest.new("AAA", "10-K"), root=tmp_path)
    time.sleep(0.01)
    enqueue(IndexRequest.new("BBB", "10-Q"), root=tmp_path)    # also P1
    time.sleep(0.01)
    enqueue(IndexRequest.new("CCC", "20-F"), root=tmp_path)    # also P1
    pending = list_pending(tmp_path)
    assert [p.ticker for p in pending] == ["AAA", "BBB", "CCC"]


def test_list_pending_backfills_priority_from_form_for_legacy_files(tmp_path: Path) -> None:
    """Queue files written before #39 lack a priority key; derive it from form."""
    legacy = {
        "id": "legacy123456",
        "ticker": "OLD",
        "form": "10-K",
        "requested_at": "2026-01-01T00:00:00+00:00",
        "model": None,
        "accession": None,
    }  # no "priority" key
    (tmp_path / "legacy123456.json").write_text(json.dumps(legacy))
    time.sleep(0.01)
    enqueue(IndexRequest.new("NEW", "8-K"), root=tmp_path)     # P2, newer
    pending = list_pending(tmp_path)
    # Legacy 10-K backfills to P1, so it sorts ahead of the newer P2 8-K.
    assert [p.ticker for p in pending] == ["OLD", "NEW"]
    assert pending[0].priority == PRIORITY_P1


def test_index_request_force_defaults_false() -> None:
    assert IndexRequest.new("NVDA").force is False


def test_index_request_force_persists_through_enqueue(tmp_path: Path) -> None:
    r = IndexRequest.new("NVDA", "10-K", force=True)
    path = enqueue(r, root=tmp_path)
    assert json.loads(path.read_text())["force"] is True
    # And survives the read-back in list_pending.
    assert list_pending(tmp_path)[0].force is True


# ---- form-policy predicates (issue #40) ------------------------------------


def test_is_high_signal_form() -> None:
    from ai_buffett_zo.indexer import is_high_signal_form
    for f in ("10-K", "10-Q", "20-F", "40-F", "DEF 14A", "8-K"):
        assert is_high_signal_form(f) is True
    for f in ("4", "SC 13G", "S-8", "144", "424B5", "ARS"):
        assert is_high_signal_form(f) is False


def test_is_administrative_form() -> None:
    from ai_buffett_zo.indexer import is_administrative_form
    for f in ("SC 13G", "S-8", "144", "424B5", "ARS", "EFFECT"):
        assert is_administrative_form(f) is True
    for f in ("10-K", "10-Q", "DEF 14A", "8-K", "4"):  # 4 is P3, not P4
        assert is_administrative_form(f) is False
