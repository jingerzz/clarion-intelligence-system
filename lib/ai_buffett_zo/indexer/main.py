"""sec-indexer service entrypoint.

Run as a Zo process-mode service. Watches `~/clarion/queue/` for ticker
requests and runs the fetch → extract → tree → save pipeline. Idempotent —
already-indexed filings (by accession) are skipped.

Auth: reads `ZO_API_KEY` from env (a Zo-issued bearer token, not a third-party
provider key). Set as a Zo service env var via Settings → Advanced → Secrets.

Logs: appends to `{sec_root}/.indexer.log` and to stderr (Zo captures stderr
into its service log stream).

CLI:
    sec-indexer                         # default roots, 5s poll interval
    sec-indexer --poll-interval 10
    sec-indexer --queue-root /path --sec-root /path
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

from ai_buffett_zo.indexer.queue import (
    DEFAULT_QUEUE_ROOT,
    claim,
    list_pending,
    mark_done,
    mark_failed,
)
from ai_buffett_zo.indexer.runtime import is_tree_stale, write_runtime_marker
from ai_buffett_zo.indexer.status import (
    FilingStatus,
    load_status,
    save_status,
)
from ai_buffett_zo.llm import DEFAULT_MODEL_INDEX, ZoClient
from ai_buffett_zo.observability import Timing, code_version
from ai_buffett_zo.secrag import (
    DEFAULT_SEC_ROOT,
    FilingNotFound,
    TreeBuilder,
    build_raw_tree,
    detect_content_type,
    extract_sections_for_form,
    fetch_filing,
    fetch_filing_by_accession,
    is_indexed,
    load_tree,
    save_raw,
    save_tree,
    should_full_index,
)
from ai_buffett_zo.secrag.recovery import recover_pointer_sections
from ai_buffett_zo.secrag.tree import DEFAULT_TREE_CONCURRENCY

DEFAULT_POLL_INTERVAL = 5.0
LOG_FILENAME = ".indexer.log"
CONCURRENCY_ENV = "CLARION_INDEX_CONCURRENCY"


def _index_concurrency() -> int:
    """Tree-build parallelism (issue #48), from CLARION_INDEX_CONCURRENCY.

    Defaults to DEFAULT_TREE_CONCURRENCY. A malformed or non-positive value
    falls back to 1 (serial) — never crash the service over a bad env var.
    """
    raw = os.environ.get(CONCURRENCY_ENV)
    if not raw:
        return DEFAULT_TREE_CONCURRENCY
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def setup_logging(sec_root: Path, *, verbose: bool = False) -> logging.Logger:
    """Configure the sec_indexer logger. File at sec_root/LOG_FILENAME + stderr."""
    sec_root.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("sec_indexer")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()  # idempotent across restarts
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(sec_root / LOG_FILENAME)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def process_one(
    request_id: str,
    *,
    queue_root: Path,
    sec_root: Path,
    client: ZoClient,
    default_model: str,
    logger: logging.Logger,
    indexer_commit: str | None = None,
) -> None:
    """Process a single queued request end-to-end. Updates queue + status.

    ``indexer_commit`` is the running code's git commit (issue #57); it's
    stamped on the produced tree and used to decide whether an already-indexed
    filing is stale and should be re-extracted.
    """
    claimed = claim(request_id, root=queue_root)
    if claimed is None:
        return

    try:
        req = json.loads(claimed.read_text())
    except json.JSONDecodeError as e:
        logger.error("malformed request %s: %s", request_id, e)
        mark_failed(request_id, f"malformed JSON: {e}", root=queue_root)
        return

    ticker = req.get("ticker", "?")
    form = req.get("form", "10-K")
    model = req.get("model") or default_model
    accession = req.get("accession")
    force = bool(req.get("force", False))

    logger.info(
        "processing %s (%s/%s%s) with %s",
        request_id,
        ticker,
        form,
        f"@{accession}" if accession else "",
        model,
    )

    status = load_status(sec_root, ticker)
    status.update_request(form=form, state="running")
    save_status(sec_root, status)

    # Per-filing timing (issue #42): record each pipeline stage so the
    # service log reveals where indexing time goes (fetch vs. LLM tree-build
    # is the usual split). Emitted as one structured line on success.
    timing = Timing()

    try:
        with timing.stage("fetch"):
            if accession:
                metadata, html = fetch_filing_by_accession(ticker, accession)
            else:
                metadata, html = fetch_filing(ticker, form=form)

        if is_indexed(sec_root, ticker, metadata.accession):
            # Already on disk. Re-extract only when forced or when the stored
            # tree was built by older code (issue #57) — otherwise skip, so a
            # routine re-index stays cheap. A tree that fails to load is treated
            # as stale and rebuilt.
            reextract = force
            if not reextract:
                try:
                    existing = load_tree(sec_root, ticker, metadata.accession)
                    reextract = is_tree_stale(existing.indexer_commit, indexer_commit)
                except Exception:  # noqa: BLE001 — unreadable tree → rebuild it
                    reextract = True
            if not reextract:
                logger.info("already indexed (current): %s %s", ticker, metadata.accession)
                status.update_request(form=form, state="completed")
                save_status(sec_root, status)
                mark_done(request_id, root=queue_root)
                return
            logger.info(
                "re-extracting %s %s (force=%s, now=%s)",
                ticker, metadata.accession, force, indexer_commit,
            )

        save_raw(sec_root, metadata, html)
        # Form-aware routing: 10-K/10-Q → curated extraction; everything else
        # (S-1, DEF 14A, Form 4 XML, etc.) → generic markdown-heading extraction.
        with timing.stage("extract"):
            content_type = detect_content_type(metadata.primary_doc)
            sections = extract_sections_for_form(
                html,
                form=metadata.form,
                content_type=content_type,
            )
        if not sections:
            raise ValueError(
                f"no sections extracted from {ticker} {form} (content_type={content_type})"
            )

        # Phase 2 recovery (issue #26): for 10-Ks where Items 7/8 are
        # incorporated-by-reference, fetch FilingSummary.xml + R-files from
        # the same accession and replace the pointer body with the
        # substantive statements. Wrapped in try/except so a network failure
        # doesn't break indexing — pointer flag stays True, recovered_via
        # stays None, search layer surfaces the gap.
        with timing.stage("recovery"):
            try:
                sections = recover_pointer_sections(metadata, sections, sec_root)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Phase 2 recovery failed for %s %s; continuing with pointer text: %s",
                    ticker, metadata.accession, e,
                )

        # Decide indexing path: full LLM-summarized tree (10-K, S-1, etc.) vs
        # raw single-node fallback (8-K, Form 4, etc.). Token-count safety net
        # forces a full index when a normally-raw form runs unusually long.
        total_tokens = sum(len(s.text) for s in sections) // 4
        with timing.stage("tree-build"):
            if should_full_index(metadata.form, total_tokens):
                builder = TreeBuilder(
                    client, model=model, max_concurrency=_index_concurrency()
                )
                tree = builder.build(metadata, sections)
            else:
                tree = build_raw_tree(metadata, sections)
                logger.info(
                    "raw-stored %s %s (form not in full-index allowlist; %d tokens)",
                    ticker, metadata.accession, total_tokens,
                )
        # Stamp the code version that produced this tree (issue #57) so a
        # future index run can tell whether it predates an extraction fix.
        tree = dataclasses.replace(tree, indexer_commit=indexer_commit)
        with timing.stage("save"):
            save_tree(sec_root, tree)

        status.merge_filing(
            FilingStatus(
                accession=metadata.accession,
                form=metadata.form,
                filed=metadata.filed.isoformat(),
                indexed_at=tree.indexed_at.isoformat(),
                status="indexed",
            )
        )
        status.update_request(form=form, state="completed")
        save_status(sec_root, status)
        mark_done(request_id, root=queue_root)
        logger.info(
            "indexed %s %s — %d sections (%d chunked)",
            ticker,
            metadata.accession,
            len(sections),
            sum(1 for s in tree.sections if s.chunks),
        )
        # Compact per-stage timing on one line, keyed by form so logs can be
        # grepped/aggregated by form type (issue #42).
        stage_str = " ".join(f"{name}={secs:.1f}s" for name, secs in timing.stages)
        logger.info(
            "timing %s %s form=%s total=%.1fs %s",
            ticker, metadata.accession, metadata.form, timing.total(), stage_str,
        )

    except FilingNotFound as e:
        logger.warning("filing not found for %s: %s", ticker, e)
        status.update_request(form=form, state="failed", error=str(e))
        save_status(sec_root, status)
        mark_failed(request_id, str(e), root=queue_root)

    except Exception as e:  # noqa: BLE001
        logger.exception("indexing failed for %s/%s", ticker, form)
        status.update_request(
            form=form, state="failed", error=f"{type(e).__name__}: {e}"
        )
        save_status(sec_root, status)
        mark_failed(request_id, f"{type(e).__name__}: {e}", root=queue_root)


def run_loop(
    *,
    queue_root: Path = DEFAULT_QUEUE_ROOT,
    sec_root: Path = DEFAULT_SEC_ROOT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    max_iterations: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    client: ZoClient | None = None,
    default_model: str = DEFAULT_MODEL_INDEX,
) -> None:
    """Main service loop.

    max_iterations: bound the loop for tests. None = run forever.
    sleep: hook for tests to skip real waits.
    client: optional pre-built ZoClient (defaults to env-driven).
    """
    logger = setup_logging(sec_root)
    client = client or ZoClient()
    # Stamp the code this process is running (issue #55). The marker lets
    # `clarion-sec-research doctor` detect a service left running on stale code
    # after a git pull — the silent failure that produced wrong re-indexed data.
    version = code_version()
    logger.info(
        "sec-indexer starting (version=%s); queue=%s sec=%s",
        version.label(), queue_root, sec_root,
    )
    write_runtime_marker(sec_root, version)

    iteration = 0
    while max_iterations is None or iteration < max_iterations:
        for req in list_pending(queue_root):
            process_one(
                req.id,
                queue_root=queue_root,
                sec_root=sec_root,
                client=client,
                default_model=default_model,
                indexer_commit=version.commit,
                logger=logger,
            )
        sleep(poll_interval)
        iteration += 1


def main() -> None:
    """Entry point for the `sec-indexer` console script."""
    ap = argparse.ArgumentParser(prog="sec-indexer")
    ap.add_argument("--queue-root", type=Path, default=DEFAULT_QUEUE_ROOT)
    ap.add_argument("--sec-root", type=Path, default=DEFAULT_SEC_ROOT)
    ap.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL)
    args = ap.parse_args()
    run_loop(
        queue_root=args.queue_root,
        sec_root=args.sec_root,
        poll_interval=args.poll_interval,
    )


if __name__ == "__main__":
    main()
