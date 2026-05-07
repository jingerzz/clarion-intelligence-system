"""Tests for ai_buffett_zo.indexer.status."""

from __future__ import annotations

from pathlib import Path

from ai_buffett_zo.indexer import (
    FilingStatus,
    TickerStatus,
    load_status,
    save_status,
    status_path,
)


def _filing(accession: str, indexed_at: str = "2026-05-06T12:00:00+00:00") -> FilingStatus:
    return FilingStatus(
        accession=accession,
        form="10-K",
        filed="2026-02-21",
        indexed_at=indexed_at,
        status="indexed",
    )


def test_load_status_empty_when_missing(tmp_path: Path) -> None:
    s = load_status(tmp_path, "NVDA")
    assert s.ticker == "NVDA"
    assert s.filings == []
    assert s.last_request is None


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    s = TickerStatus(ticker="NVDA")
    s.merge_filing(_filing("acc-1"))
    s.update_request(form="10-K", state="completed")
    save_status(tmp_path, s)

    loaded = load_status(tmp_path, "NVDA")
    assert loaded.ticker == "NVDA"
    assert len(loaded.filings) == 1
    assert loaded.filings[0].accession == "acc-1"
    assert loaded.last_request is not None
    assert loaded.last_request["state"] == "completed"
    assert loaded.last_request["form"] == "10-K"


def test_status_path_uppercases_ticker(tmp_path: Path) -> None:
    assert status_path(tmp_path, "nvda").parts[-2] == "NVDA"
    assert status_path(tmp_path, "NVDA").parts[-2] == "NVDA"


def test_merge_filing_replaces_by_accession() -> None:
    s = TickerStatus(ticker="NVDA")
    s.merge_filing(_filing("acc-1", indexed_at="2026-01-01T00:00:00+00:00"))
    s.merge_filing(_filing("acc-1", indexed_at="2026-05-06T00:00:00+00:00"))
    assert len(s.filings) == 1
    assert s.filings[0].indexed_at == "2026-05-06T00:00:00+00:00"


def test_merge_filing_appends_new_accession() -> None:
    s = TickerStatus(ticker="NVDA")
    s.merge_filing(_filing("acc-1"))
    s.merge_filing(_filing("acc-2"))
    assert {f.accession for f in s.filings} == {"acc-1", "acc-2"}


def test_update_request_records_error() -> None:
    s = TickerStatus(ticker="NVDA")
    s.update_request(form="10-K", state="failed", error="ticker not found")
    assert s.last_request is not None
    assert s.last_request["state"] == "failed"
    assert s.last_request["error"] == "ticker not found"
    assert s.last_request["updated_at"]


def test_save_creates_parent_dir(tmp_path: Path) -> None:
    """save_status should mkdir the per-ticker subdir if missing."""
    s = TickerStatus(ticker="MSFT")
    save_status(tmp_path, s)
    assert (tmp_path / "MSFT").is_dir()
    assert (tmp_path / "MSFT" / ".status.json").exists()
