#!/usr/bin/env python3
"""Clarion SEC research — index / search / status.

Subcommands:
    index TICKER                      queue a broad eval-ready set: latest 2
                                      10-Ks + latest 3 10-Qs + ALL filings in
                                      the last 90 days (Form 4, 8-K, etc.),
                                      deduped by accession.
    index TICKER --form FORM          queue ALL filings of FORM in the last
                                      90 days (override window with --days N
                                      or --count N; use --latest for a single
                                      most-recent filing).
    search "query" [--tickers ...] [--sections ...] [--top-k N]
    status TICKER                     show indexing state for a ticker

Reads from ~/clarion/queue (queue) and ~/clarion/sec (corpus). Override via
$CLARION_QUEUE_ROOT and $CLARION_SEC_ROOT for testing or non-default layouts.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ai_buffett_zo.indexer import (
    DEFAULT_QUEUE_ROOT,
    IndexRequest,
    assess_coverage,
    enqueue,
    indexer_health,
    is_high_signal_form,
    load_status,
)
from ai_buffett_zo.secrag import (
    DEFAULT_SEC_ROOT,
    FilingMetadata,
    FilingNotFound,
    SearchHit,
    list_indexed,
    list_recent_filings,
    search,
)
from ai_buffett_zo.voice import (
    cite_filing,
    footer,
    header,
    md_table,
    no_data,
)


def queue_root() -> Path:
    return Path(os.environ.get("CLARION_QUEUE_ROOT") or DEFAULT_QUEUE_ROOT)


def sec_root() -> Path:
    return Path(os.environ.get("CLARION_SEC_ROOT") or DEFAULT_SEC_ROOT)


# ---- index -----------------------------------------------------------------


DEFAULT_INDEX_DAYS = 90
DEFAULT_COMPOSITE_10K_COUNT = 2
DEFAULT_COMPOSITE_10Q_COUNT = 3
DEFAULT_COMPOSITE_DEF14A_COUNT = 1   # latest proxy (governance/comp) for eval-readiness
DEFAULT_COMPOSITE_FORM4_COUNT = 3    # "selected" recent insider Form 4s in the eval profile (#40)
INDEX_PROFILES = ("eval", "full")    # eval = high-signal default; full = all forms (#40)


def cmd_index(args: argparse.Namespace) -> int:
    # CLI validation: --latest is exclusive with --days/--count.
    if args.latest and (args.days is not None or args.count is not None):
        print("ERROR: --latest is mutually exclusive with --days and --count.", file=sys.stderr)
        return 2

    qroot = queue_root()
    qroot.mkdir(parents=True, exist_ok=True)

    # --- Legacy single-filing path: --latest preserves "index the most recent"
    # behavior. The indexer resolves form → latest filing internally.
    if args.latest:
        if not args.form:
            print("ERROR: --latest requires --form FORM.", file=sys.stderr)
            return 2
        req = IndexRequest.new(args.ticker, form=args.form, force=args.force)
        enqueue(req, root=qroot)
        _print_index_summary(args.ticker, [(req.form, None, None, req.id)], mode="latest")
        return 0

    # --- Multi-filing paths: enumerate target filings via SEC EDGAR, enqueue one
    # IndexRequest per accession.
    try:
        targets = _build_index_targets(
            args.ticker,
            form=args.form,
            days=args.days,
            count=args.count,
            profile=args.profile,
        )
    except FilingNotFound as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if not targets:
        scope = _scope_label(args.form, args.days, args.count, args.profile)
        print(no_data(f"No filings found for {args.ticker} matching {scope}."))
        return 0

    queued: list[tuple[str, str, str, str]] = []
    for filing in targets:
        req = IndexRequest.new(
            args.ticker,
            form=filing.form,
            accession=filing.accession,
            force=args.force,
        )
        enqueue(req, root=qroot)
        queued.append((filing.form, filing.filed.isoformat(), filing.accession, req.id))

    _print_index_summary(args.ticker, queued, mode="composite" if args.form is None else "form")
    return 0


def _build_index_targets(
    ticker: str,
    *,
    form: str | None,
    days: int | None,
    count: int | None,
    profile: str = "eval",
) -> list[FilingMetadata]:
    """Resolve CLI flags to a deduped list of FilingMetadata to enqueue.

    Composite default (no ``--form``), by ``profile`` (issue #40):

    - ``eval`` (default): the high-signal set for a first-pass evaluation —
      last 2 10-Ks + last 3 10-Qs + latest DEF 14A, plus only high-signal forms
      (10-K/10-Q/20-F/40-F/DEF 14A/8-K) from the 90-day window, plus the latest
      few insider Form 4s. Administrative/registration forms (13D/G, S-8, 144,
      424B, EFFECT, ARS, …) are deferred.
    - ``full``: the eval set plus **all** remaining forms from the 90-day window
      (comprehensive diligence).

    Single-form mode (``--form X``): all filings of X in the window (default
    90 days, override with ``--days N`` or ``--count N``); ``profile`` is N/A.
    """
    if form is None:
        merged: dict[str, FilingMetadata] = {}
        # Core, fetched explicitly so coverage holds even outside the 90d window.
        for f, n in (
            ("10-K", DEFAULT_COMPOSITE_10K_COUNT),
            ("10-Q", DEFAULT_COMPOSITE_10Q_COUNT),
            ("DEF 14A", DEFAULT_COMPOSITE_DEF14A_COUNT),
        ):
            for fm in list_recent_filings(ticker, form=f, limit=n):
                merged.setdefault(fm.accession, fm)
        # 90-day window: every form for `full`, only high-signal for `eval`.
        for fm in list_recent_filings(ticker, since_days=DEFAULT_INDEX_DAYS):
            if profile == "full" or is_high_signal_form(fm.form):
                merged.setdefault(fm.accession, fm)
        # eval keeps a capped set of recent insider Form 4s (the 90d sweep
        # filtered them out as low-signal); full already has them via the sweep.
        if profile == "eval":
            for fm in list_recent_filings(ticker, form="4", limit=DEFAULT_COMPOSITE_FORM4_COUNT):
                merged.setdefault(fm.accession, fm)
        return sorted(merged.values(), key=lambda fm: fm.filed, reverse=True)

    # Single-form mode. --count and --days are independent filters; default
    # window is 90 days when neither is given.
    if days is None and count is None:
        days = DEFAULT_INDEX_DAYS
    return list_recent_filings(ticker, form=form, since_days=days, limit=count)


def _scope_label(form: str | None, days: int | None, count: int | None, profile: str = "eval") -> str:
    if form is None:
        if profile == "full":
            return f"full profile (2x 10-K + 3x 10-Q + proxy + ALL forms in last {DEFAULT_INDEX_DAYS} days)"
        return (
            f"eval profile (2x 10-K + 3x 10-Q + proxy + 8-K & high-signal forms in last "
            f"{DEFAULT_INDEX_DAYS} days + latest {DEFAULT_COMPOSITE_FORM4_COUNT} Form 4)"
        )
    parts = [f"form={form}"]
    if days is not None:
        parts.append(f"last {days} days")
    if count is not None:
        parts.append(f"limit {count}")
    if days is None and count is None:
        parts.append(f"last {DEFAULT_INDEX_DAYS} days")
    return ", ".join(parts)


def _print_index_summary(
    ticker: str,
    queued: list[tuple[str, str | None, str | None, str]],
    *,
    mode: str,
) -> None:
    """Render the user-facing confirmation. ``queued`` rows are
    (form, filed, accession, request_id); filed/accession may be None for
    --latest where the accession isn't known until the indexer fetches.
    """
    n = len(queued)
    title = f"Queued — {ticker} ({n} filing{'s' if n != 1 else ''})"
    parts: list[str] = [header(title), ""]

    if mode == "latest":
        form = queued[0][0]
        req_id = queued[0][3]
        parts.append(
            f"Request `{req_id}` will index the **most recent {form}** for {ticker}. "
            f"The sec-indexer service typically takes 1-5 minutes per filing."
        )
    else:
        descr = "composite default set" if mode == "composite" else "form-scoped set"
        parts.append(
            f"Enqueued {n} filing{'s' if n != 1 else ''} for {ticker} ({descr}). "
            f"The sec-indexer service will work through them in order; expect "
            f"1-5 minutes per filing."
        )
        parts.append("")
        rows = [
            [form, filed or "", accession or "", req_id]
            for form, filed, accession, req_id in queued
        ]
        parts.append(md_table(["Form", "Filed", "Accession", "Request ID"], rows))

    parts.append("")
    parts.append("Check progress with:")
    parts.append("")
    parts.append("```")
    parts.append(f"clarion-sec-research status {ticker}")
    parts.append("```")
    parts.append("")
    parts.append(footer())
    print("\n".join(parts))


# ---- search ----------------------------------------------------------------


def cmd_search(args: argparse.Namespace) -> int:
    sroot = sec_root()
    tickers = _split_csv(args.tickers)
    sections = _split_csv(args.sections)

    hits = search(
        args.query,
        root=sroot,
        tickers=tickers,
        section_labels=sections,
        top_k=args.top_k,
    )

    print(header(f'SEC search — "{args.query}"', _query_subtitle(tickers, sections)))

    if not hits:
        print()
        print(no_data("no matches in the indexed corpus."))
        _suggest_indexing(sroot, tickers)
        return 0

    print()
    print(_hits_table(hits))
    print()
    print("**Top results**")
    for i, h in enumerate(hits[: args.top_show], start=1):
        print()
        print(f"### {i}. {cite_filing(h.ticker, h.form, h.filed)} → `{h.path}`")
        print()
        print(f"> {h.snippet}")

    print()
    print(footer(source_lines=[h.citation for h in hits[: args.top_show]]))
    return 0


def _hits_table(hits: list[SearchHit]) -> str:
    rows = [
        [h.ticker, h.form, h.filed, h.section_label, f"{h.score:.0f}"]
        for h in hits
    ]
    return md_table(["Ticker", "Form", "Filed", "Section", "Score"], rows)


def _suggest_indexing(sroot: Path, tickers: list[str] | None) -> None:
    if tickers:
        print()
        print("To index these tickers, run:")
        for t in tickers:
            print(f"```\nclarion-sec-research index {t.upper()}\n```")
    else:
        indexed = list_indexed(sroot)
        if not indexed:
            print()
            print("No filings indexed yet. Index one with:")
            print("```\nclarion-sec-research index <TICKER>\n```")


def _query_subtitle(
    tickers: list[str] | None, sections: list[str] | None
) -> str | None:
    parts: list[str] = []
    if tickers:
        parts.append(f"tickers: {', '.join(tickers)}")
    if sections:
        parts.append(f"sections: {', '.join(sections)}")
    return " · ".join(parts) if parts else None


def _split_csv(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [s.strip() for s in raw.split(",") if s.strip()]


# ---- status ----------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    sroot = sec_root()
    status = load_status(sroot, args.ticker)

    print(header(f"Indexing status — {status.ticker}"))

    if not status.filings and not status.last_request:
        print()
        print(f"No filings indexed yet for {status.ticker}.")
        print(f"Run: `clarion-sec-research index {status.ticker}`")
        print()
        print(footer())
        return 0

    if status.last_request:
        lr = status.last_request
        print()
        print("**Last request**")
        print(f"- Form: `{lr.get('form', '?')}`")
        print(f"- State: `{lr.get('state', '?')}`")
        print(f"- Updated: `{lr.get('updated_at', '?')}`")
        if lr.get("error"):
            print(f"- Error: `{lr['error']}`")

    if status.filings:
        indexed = [f for f in status.filings if f.status in ("indexed", "raw_only")]
        cov = assess_coverage(status.ticker, [f.form for f in indexed])
        print()
        print("**Eval readiness**")
        if cov.eval_ready:
            print(f"- Ready to evaluate — annual report (`{cov.core_form}`) indexed.")
        else:
            print("- Not eval-ready yet — annual report (10-K / 20-F) not indexed.")
        gaps = cov.missing()
        if gaps:
            print(f"- High-signal gaps: {', '.join(gaps)}.")

        print()
        print("**Indexed filings**")
        rows = [
            [f.form, f.filed, f.accession, f.indexed_at, f.status]
            for f in status.filings
        ]
        print(md_table(["Form", "Filed", "Accession", "Indexed at", "Status"], rows))

    print()
    print(footer())
    return 0


# ---- reindex ---------------------------------------------------------------


def cmd_reindex(args: argparse.Namespace) -> int:
    """Re-enqueue indexed filings for re-extraction (issue #57).

    No ticker → every indexed filing; a ticker → just that one's. By default the
    indexer re-extracts only filings built by older code (current ones skip), so
    this is the safe "apply the latest extraction fixes to my corpus" command
    after an upgrade. ``--force`` re-extracts everything regardless.
    """
    sroot = sec_root()
    qroot = queue_root()
    qroot.mkdir(parents=True, exist_ok=True)

    ticker = args.ticker.upper() if args.ticker else None
    indexed = list_indexed(sroot, ticker=ticker)
    if not indexed:
        print(no_data(f"No indexed filings found for {ticker or 'any ticker'}."))
        return 0

    rows = []
    for m in indexed:
        req = IndexRequest.new(m.ticker, form=m.form, accession=m.accession, force=args.force)
        enqueue(req, root=qroot)
        rows.append([m.ticker, m.form, m.accession])

    print(header("Re-index queued"))
    print()
    verb = "force-re-extract" if args.force else "refresh if built by older code"
    print(f"Queued {len(rows)} filing(s) to {verb}.")
    print()
    print(md_table(["Ticker", "Form", "Accession"], rows))
    print()
    print(
        "The indexer processes these in priority order (10-Ks first); filings "
        "already on the current code are skipped, so this is safe to re-run."
    )
    print()
    print(footer())
    return 0


# ---- doctor ----------------------------------------------------------------


def cmd_doctor(_args: argparse.Namespace) -> int:
    """Report whether the running sec-indexer is on the installed code (#55)."""
    health = indexer_health(sec_root())
    print(header("SEC indexer health"))
    print()
    print(f"- {health.message()}")
    if health.stale:
        print()
        print(
            "Restart the `sec-indexer` service (re-run `set up Clarion`, or restart "
            "the service directly), then re-index anything indexed since the update — "
            "those filings were processed by the old code."
        )
    print()
    print(footer())
    # Non-zero exit on staleness so callers/CI can gate on it.
    return 1 if health.stale else 0


# ---- main ------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(prog="clarion-sec-research")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_index = sub.add_parser(
        "index",
        help=(
            "Queue filings for indexing. With no flags: composite default set "
            "(latest 2 10-Ks, latest 3 10-Qs, all forms in last 90 days). "
            "With --form X: all filings of X in last 90 days (override with "
            "--days/--count; --latest for single most-recent)."
        ),
    )
    p_index.add_argument("ticker", type=str.upper)
    p_index.add_argument(
        "--form",
        default=None,
        help=(
            "SEC form name (e.g. 10-K, 10-Q, 4, 8-K, S-1, 'DEF 14A'). When set, "
            "indexes all filings of this form within the chosen window. When "
            "omitted, runs the composite default."
        ),
    )
    p_index.add_argument(
        "--days",
        type=int,
        default=None,
        help="Window in days for --form X (default 90 when --form is set).",
    )
    p_index.add_argument(
        "--count",
        type=int,
        default=None,
        help="Cap the most-recent N filings (combines with --days as an AND filter).",
    )
    p_index.add_argument(
        "--latest",
        action="store_true",
        help=(
            "Legacy single-result mode: enqueue only the single most-recent "
            "filing of --form. Mutually exclusive with --days and --count."
        ),
    )
    p_index.add_argument(
        "--force",
        action="store_true",
        help="Re-extract even if already indexed (issue #57). Default skips current filings.",
    )
    p_index.add_argument(
        "--profile",
        choices=INDEX_PROFILES,
        default="eval",
        help=(
            "Composite-default form policy (issue #40). 'eval' (default): high-signal "
            "filings for a first-pass evaluation (10-K/10-Q/20-F/DEF 14A/8-K + recent "
            "Form 4). 'full': everything, incl. administrative/registration forms "
            "(13G/D, S-8, 144, 424B, EFFECT, ARS). Ignored with --form."
        ),
    )
    p_index.set_defaults(func=cmd_index)

    p_reindex = sub.add_parser(
        "reindex",
        help=(
            "Re-extract already-indexed filings to apply the latest extraction "
            "fixes (issue #57). No ticker = whole corpus. Only filings built by "
            "older code are re-extracted unless --force."
        ),
    )
    p_reindex.add_argument(
        "ticker", nargs="?", default=None, type=str.upper,
        help="Limit to one ticker (default: every indexed filing).",
    )
    p_reindex.add_argument(
        "--force",
        action="store_true",
        help="Re-extract every filing, not just those built by older code.",
    )
    p_reindex.set_defaults(func=cmd_reindex)

    p_search = sub.add_parser("search", help="Search indexed filings by keyword.")
    p_search.add_argument("query")
    p_search.add_argument("--tickers", help="Comma-separated tickers (filter).")
    p_search.add_argument(
        "--sections",
        help=(
            "Comma-separated section labels. For 10-K/10-Q the canonical labels "
            "are: business, risk_factors, mdna, financial_statements. For other "
            "forms (Form 4, 8-K, S-1, DEF 14A, ...) sections are slugified from "
            "each filing's headings — run search without --sections first to see "
            "what's indexed."
        ),
    )
    p_search.add_argument("--top-k", type=int, default=10)
    p_search.add_argument(
        "--top-show",
        type=int,
        default=5,
        help="How many full-snippet entries to render after the table.",
    )
    p_search.set_defaults(func=cmd_search)

    p_status = sub.add_parser("status", help="Show indexing status for a ticker.")
    p_status.add_argument("ticker", type=str.upper)
    p_status.set_defaults(func=cmd_status)

    p_doctor = sub.add_parser(
        "doctor",
        help="Check the running sec-indexer is on the installed code (issue #55).",
    )
    p_doctor.set_defaults(func=cmd_doctor)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
