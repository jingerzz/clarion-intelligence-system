"""Tests for ai_buffett_zo.indexer.main.

The full pipeline (fetch_filing, TreeBuilder, extract_sections) is mocked
at the import-site in main.py. ZoClient is constructed but never called —
TreeBuilder is replaced with a fake that returns a controlled FilingTree.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from ai_buffett_zo.indexer import (
    IndexRequest,
    enqueue,
    list_pending,
    load_status,
)
from ai_buffett_zo.indexer import main as main_mod
from ai_buffett_zo.llm import ZoClient
from ai_buffett_zo.secrag import (
    FilingMetadata,
    FilingNotFound,
    FilingTree,
    Section,
    SectionNode,
)


def _logger() -> logging.Logger:
    return logging.getLogger("test_indexer")


def _meta(ticker: str = "NVDA", accession: str = "acc-1") -> FilingMetadata:
    return FilingMetadata(
        cik="0000000000",
        ticker=ticker,
        company=f"{ticker} Inc.",
        form="10-K",
        filed=date(2026, 2, 21),
        period=date(2026, 1, 26),
        accession=accession,
        primary_doc="x.htm",
        primary_doc_url="https://example/x.htm",
    )


def _tree(metadata: FilingMetadata) -> FilingTree:
    return FilingTree(
        metadata=metadata,
        sections=[
            SectionNode(
                label="risk_factors",
                title="Item 1A",
                text="Risk text.",
                summary="Risks.",
                summary_data={"severity": 2},
                chunks=[],
            )
        ],
        indexed_at=datetime(2026, 5, 6, tzinfo=UTC),
        indexer_model="zo:openai/gpt-5.4-mini",
    )


def _section() -> Section:
    return Section(
        label="risk_factors",
        title="Item 1A",
        text="Some risk text.",
        char_start=0,
        char_end=15,
    )


def _patch_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    metadata: FilingMetadata | None = None,
    sections: list[Section] | None = None,
    fetch_raises: Exception | None = None,
) -> dict[str, Any]:
    """Install fakes for fetch_filing, extract_sections_for_form, TreeBuilder."""
    captured: dict[str, Any] = {"fetched": [], "extracted": [], "built": []}
    md = metadata or _meta()
    secs = sections if sections is not None else [_section()]

    def fake_fetch(ticker: str, *, form: str = "10-K") -> tuple[FilingMetadata, str]:
        captured["fetched"].append((ticker, form))
        if fetch_raises:
            raise fetch_raises
        return md, "<html>raw</html>"

    def fake_extract_for_form(content: str, *, form: str, content_type: str = "html") -> list[Section]:
        captured["extracted"].append((content, form, content_type))
        return secs

    class FakeBuilder:
        def __init__(
            self, client: Any, *, model: str = "x", max_concurrency: int = 1
        ) -> None:
            self.client = client
            self.model = model
            self.max_concurrency = max_concurrency

        def build(self, metadata: FilingMetadata, sections: list[Section]) -> FilingTree:
            captured["built"].append((metadata, sections))
            return _tree(metadata)

    monkeypatch.setattr(main_mod, "fetch_filing", fake_fetch)
    monkeypatch.setattr(main_mod, "extract_sections_for_form", fake_extract_for_form)
    monkeypatch.setattr(main_mod, "TreeBuilder", FakeBuilder)
    return captured


# ---- process_one happy path ------------------------------------------------


def test_process_one_indexes_filing_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue_root = tmp_path / "queue"
    sec_root = tmp_path / "sec"
    captured = _patch_pipeline(monkeypatch)

    r = IndexRequest.new("NVDA", "10-K")
    enqueue(r, root=queue_root)

    main_mod.process_one(
        r.id,
        queue_root=queue_root,
        sec_root=sec_root,
        client=ZoClient(token="zo_sk_test"),
        default_model="zo:openai/gpt-5.4-mini",
        logger=_logger(),
    )

    # Pipeline ran
    assert captured["fetched"] == [("NVDA", "10-K")]
    assert captured["built"]

    # Tree saved
    tree_file = sec_root / "NVDA" / "acc-1.tree.json.gz"
    assert tree_file.exists()
    raw_file = sec_root / "NVDA" / "acc-1.raw.html.gz"
    assert raw_file.exists()

    # Status updated
    status = load_status(sec_root, "NVDA")
    assert len(status.filings) == 1
    assert status.filings[0].accession == "acc-1"
    assert status.last_request is not None
    assert status.last_request["state"] == "completed"

    # Queue: moved to .done
    assert (queue_root / ".done" / f"{r.id}.json").exists()
    assert not (queue_root / f"{r.id}.json").exists()


def test_process_one_with_accession_routes_to_fetch_by_accession(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the request carries an accession, the indexer fetches that specific
    filing — not the latest. The fetch-by-accession path is what makes the
    multi-filing index sweep in research.py possible.
    """
    queue_root = tmp_path / "queue"
    sec_root = tmp_path / "sec"
    captured = _patch_pipeline(monkeypatch)

    # Wire a separate stub for fetch_filing_by_accession that returns metadata
    # at the *requested* accession (not the default "acc-1" from _meta()).
    targeted_meta = _meta(accession="acc-targeted")

    def fake_fetch_by_accession(
        ticker: str, accession: str
    ) -> tuple[FilingMetadata, str]:
        captured.setdefault("fetched_by_accession", []).append((ticker, accession))
        return targeted_meta, "<html>targeted</html>"

    monkeypatch.setattr(main_mod, "fetch_filing_by_accession", fake_fetch_by_accession)

    r = IndexRequest.new("NVDA", "10-K", accession="acc-targeted")
    enqueue(r, root=queue_root)

    main_mod.process_one(
        r.id,
        queue_root=queue_root,
        sec_root=sec_root,
        client=ZoClient(token="zo_sk_test"),
        default_model="zo:openai/gpt-5.4-mini",
        logger=_logger(),
    )

    # Accession path was taken; the legacy fetch_filing path was NOT.
    assert captured.get("fetched_by_accession") == [("NVDA", "acc-targeted")]
    assert captured["fetched"] == []  # latest-fetch path skipped

    # The targeted accession landed in status
    status = load_status(sec_root, "NVDA")
    assert any(f.accession == "acc-targeted" for f in status.filings)


def test_process_one_skips_already_indexed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the accession is already on disk, skip rebuild (still mark done)."""
    queue_root = tmp_path / "queue"
    sec_root = tmp_path / "sec"
    captured = _patch_pipeline(monkeypatch)

    # Pre-write a tree at the same accession the fake fetch returns
    from ai_buffett_zo.secrag import save_tree

    save_tree(sec_root, _tree(_meta()))

    r = IndexRequest.new("NVDA", "10-K")
    enqueue(r, root=queue_root)

    main_mod.process_one(
        r.id,
        queue_root=queue_root,
        sec_root=sec_root,
        client=ZoClient(token="zo_sk_test"),
        default_model="zo:openai/gpt-5.4-mini",
        logger=_logger(),
    )

    # fetch happened (we need metadata), but build did NOT
    assert captured["fetched"]
    assert captured["built"] == []

    status = load_status(sec_root, "NVDA")
    assert status.last_request is not None
    assert status.last_request["state"] == "completed"
    assert (queue_root / ".done" / f"{r.id}.json").exists()


# ---- process_one failure paths ---------------------------------------------


def test_process_one_marks_failed_on_filing_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue_root = tmp_path / "queue"
    sec_root = tmp_path / "sec"
    _patch_pipeline(monkeypatch, fetch_raises=FilingNotFound("ticker fake"))

    r = IndexRequest.new("FAKE", "10-K")
    enqueue(r, root=queue_root)

    main_mod.process_one(
        r.id,
        queue_root=queue_root,
        sec_root=sec_root,
        client=ZoClient(token="zo_sk_test"),
        default_model="zo:openai/gpt-5.4-mini",
        logger=_logger(),
    )

    failed_file = queue_root / ".failed" / f"{r.id}.json"
    assert failed_file.exists()

    status = load_status(sec_root, "FAKE")
    assert status.last_request is not None
    assert status.last_request["state"] == "failed"
    assert "ticker fake" in (status.last_request["error"] or "")


def test_process_one_marks_failed_on_no_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue_root = tmp_path / "queue"
    sec_root = tmp_path / "sec"
    _patch_pipeline(monkeypatch, sections=[])

    r = IndexRequest.new("NVDA", "10-K")
    enqueue(r, root=queue_root)

    main_mod.process_one(
        r.id,
        queue_root=queue_root,
        sec_root=sec_root,
        client=ZoClient(token="zo_sk_test"),
        default_model="zo:openai/gpt-5.4-mini",
        logger=_logger(),
    )

    assert (queue_root / ".failed" / f"{r.id}.json").exists()
    status = load_status(sec_root, "NVDA")
    assert status.last_request is not None
    assert status.last_request["state"] == "failed"
    assert "no sections extracted" in (status.last_request["error"] or "")


def test_process_one_returns_silently_when_request_id_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the request file disappears before claim (rare), process_one is a no-op."""
    _patch_pipeline(monkeypatch)
    main_mod.process_one(
        "no-such-id",
        queue_root=tmp_path / "queue",
        sec_root=tmp_path / "sec",
        client=ZoClient(token="zo_sk_test"),
        default_model="zo:openai/gpt-5.4-mini",
        logger=_logger(),
    )
    # No raise, no files created (queue/sec dirs may be created by status logging — that's fine)


# ---- per-filing timing (issue #42) ----------------------------------------


def test_process_one_emits_timing_log_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A successful index emits one compact per-stage timing line, keyed by form."""
    queue_root = tmp_path / "queue"
    sec_root = tmp_path / "sec"
    _patch_pipeline(monkeypatch)

    r = IndexRequest.new("NVDA", "10-K")
    enqueue(r, root=queue_root)

    with caplog.at_level(logging.INFO, logger="test_indexer"):
        main_mod.process_one(
            r.id,
            queue_root=queue_root,
            sec_root=sec_root,
            client=ZoClient(token="zo_sk_test"),
            default_model="zo:openai/gpt-5.4-mini",
            logger=_logger(),
        )

    timing_lines = [m for m in caplog.messages if m.startswith("timing ")]
    assert len(timing_lines) == 1
    line = timing_lines[0]
    # Keyed by ticker, accession, form; carries total + each stage
    assert "NVDA" in line
    assert "acc-1" in line
    assert "form=10-K" in line
    assert "total=" in line
    for stage in ("fetch=", "extract=", "recovery=", "tree-build=", "save="):
        assert stage in line, f"missing {stage} in timing line: {line}"


# ---- run_loop --------------------------------------------------------------


def test_run_loop_processes_pending_then_sleeps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue_root = tmp_path / "queue"
    sec_root = tmp_path / "sec"
    _patch_pipeline(monkeypatch)

    enqueue(IndexRequest.new("NVDA", "10-K"), root=queue_root)
    enqueue(IndexRequest.new("AAPL", "10-K"), root=queue_root)

    sleeps: list[float] = []

    def fake_sleep(s: float) -> None:
        sleeps.append(s)

    main_mod.run_loop(
        queue_root=queue_root,
        sec_root=sec_root,
        poll_interval=7.5,
        max_iterations=1,
        sleep=fake_sleep,
        client=ZoClient(token="zo_sk_test"),
    )

    # Both processed, queue is empty (in pending dir)
    assert list_pending(queue_root) == []
    assert sleeps == [7.5]


# ---- tree-build concurrency knob (issue #48) --------------------------------


def test_index_concurrency_defaults_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(main_mod.CONCURRENCY_ENV, raising=False)
    assert main_mod._index_concurrency() == main_mod.DEFAULT_TREE_CONCURRENCY


def test_index_concurrency_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(main_mod.CONCURRENCY_ENV, "8")
    assert main_mod._index_concurrency() == 8


def test_index_concurrency_bad_value_falls_back_to_serial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(main_mod.CONCURRENCY_ENV, "garbage")
    assert main_mod._index_concurrency() == 1
    monkeypatch.setenv(main_mod.CONCURRENCY_ENV, "0")
    assert main_mod._index_concurrency() == 1


def test_run_loop_writes_runtime_marker(tmp_path: Path) -> None:
    """run_loop stamps the running code version at startup (issue #55)."""
    queue_root = tmp_path / "queue"
    sec_root = tmp_path / "sec"
    main_mod.run_loop(
        queue_root=queue_root,
        sec_root=sec_root,
        max_iterations=0,          # startup only; no queue processing
        sleep=lambda _s: None,
        client=ZoClient(token="zo_sk_test"),
    )
    marker = sec_root / ".indexer_runtime.json"
    assert marker.exists()
