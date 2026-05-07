"""Tests for ai_buffett_zo.indexer.queue."""

from __future__ import annotations

import json
import time
from pathlib import Path

from ai_buffett_zo.indexer import (
    IndexRequest,
    claim,
    enqueue,
    list_pending,
    mark_done,
    mark_failed,
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
