#!/usr/bin/env python3
"""Clarion single-stock evaluation — Buffett lens over indexed filings + market data.

Reads:
- yfinance .info for the quality snapshot
- regime.snapshot for SPY/TLT/RSP color and equity hurdle
- secrag.search for filing snippets across four Buffett dimensions

Outputs structured markdown that the Zo chat agent reasons over to produce
a Buffett-style evaluation. The script does not synthesize a thesis itself —
the SKILL.md instructs Zo to compose using the question-bank reference.

Usage:
    python eval.py NVDA
    python eval.py NVDA --rf-rate-pct 4.5
    python eval.py NVDA --no-regime
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta
from pathlib import Path

from ai_buffett_zo.data import EquityStore
from ai_buffett_zo.evaluation import (
    Fundamentals,
    LensView,
    fetch_fundamentals,
    view as lens_view,
)
from ai_buffett_zo.indexer import Coverage, assess_coverage, is_administrative_form
from ai_buffett_zo.observability import Timing
from ai_buffett_zo.regime import HURDLE_PREMIUM_PCT, RegimeSnapshot, snapshot
from ai_buffett_zo.secrag import DEFAULT_SEC_ROOT, list_indexed
from ai_buffett_zo.voice import (
    cite_quote,
    footer,
    header,
    md_table,
    no_data,
    show_math,
)


def sec_root() -> Path:
    return Path(os.environ.get("CLARION_SEC_ROOT") or DEFAULT_SEC_ROOT)


def run(args: argparse.Namespace) -> int:
    ticker = args.ticker.upper()
    sroot = sec_root()
    timing = Timing()

    with timing.stage("SEC status"):
        indexed = [m for m in list_indexed(sroot) if m.ticker == ticker]
    if not indexed:
        print(header(f"Single-Stock Evaluation — {ticker}"))
        print()
        print(no_data(f"No filings indexed for {ticker}."))
        print()
        print(f"Run `clarion-sec-research index {ticker}` first, wait for completion, then retry.")
        print()
        print(footer())
        _emit_timing(args, timing)
        return 0

    # Eval-readiness (issue #38): the eval rests on the annual report. If only
    # low-signal filings (8-K, Form 4) have indexed so far, say so up front so
    # the user can read the verdict with the right weight — and knows to wait
    # for the 10-K rather than retrying blind.
    coverage = assess_coverage(ticker, [m.form for m in indexed])
    # Disclose when low-signal/administrative forms aren't in the corpus (#40) —
    # the default `index` profile defers them; the eval should say so.
    low_signal_deferred = not any(is_administrative_form(m.form) for m in indexed)

    try:
        with timing.stage("yfinance snapshot"):
            f = fetch_fundamentals(ticker)
    except Exception as e:  # noqa: BLE001
        print(f"EVAL_ERROR: failed to fetch fundamentals for {ticker}: {type(e).__name__}: {e}")
        _emit_timing(args, timing)
        return 1

    if args.no_regime:
        regime_snap = None
    else:
        with timing.stage("regime check"):
            regime_snap = _maybe_regime(args.rf_rate_pct)

    with timing.stage("Buffett lens search"):
        lens = lens_view(ticker, sec_root=sroot)

    with timing.stage("render"):
        _render(
            f,
            regime_snap,
            lens,
            coverage=coverage,
            low_signal_deferred=low_signal_deferred,
            indexed_accessions=[m.accession for m in indexed],
        )

    _emit_timing(args, timing)
    return 0


def _emit_timing(args: argparse.Namespace, timing: Timing) -> None:
    """Print the timing summary to stderr when --timing is set.

    stderr (not stdout) so the structured markdown the chat agent parses
    stays clean — timing is operator diagnostics, not part of the eval.
    """
    if getattr(args, "timing", False):
        print(timing.summary(title=f"Timing ({args.ticker.upper()})"), file=sys.stderr)


def _maybe_regime(rf_rate_pct: float | None) -> RegimeSnapshot | None:
    """Best-effort regime snapshot. Non-fatal on failure — eval still runs."""
    try:
        store = EquityStore()
        spy = store.history("SPY", max_age=timedelta(hours=24))
        tlt = store.history("TLT", max_age=timedelta(hours=24))
        rsp = store.history("RSP", max_age=timedelta(hours=24))
    except Exception:  # noqa: BLE001
        return None
    if not spy or not tlt or not rsp:
        return None
    try:
        return snapshot(spy, tlt, rsp, rf_rate_pct=rf_rate_pct)
    except ValueError:
        return None


# ---- rendering --------------------------------------------------------------


def _render(
    f: Fundamentals,
    regime_snap: RegimeSnapshot | None,
    lens: list[LensView],
    *,
    coverage: Coverage,
    low_signal_deferred: bool = False,
    indexed_accessions: list[str],
) -> None:
    print(header(f"Single-Stock Evaluation — {f.ticker}", f.company))
    print()

    _render_coverage(coverage, low_signal_deferred=low_signal_deferred)

    if regime_snap is not None:
        _render_market_context(regime_snap)
        print()

    _render_quality_snapshot(f)
    print()

    print("## Buffett lens")
    print()
    print("*Snippets from indexed SEC filings, grouped by dimension.*")
    print()
    for lv in lens:
        _render_lens_view(lv)

    print("## Reading guide")
    print()
    print(_reading_guide(regime_snap))
    print()

    sources: list[str] = []
    if regime_snap is not None:
        sources.append(cite_quote("SPY/TLT/RSP daily bars (yfinance)", regime_snap.asof.isoformat()))
    sources.append(f"{f.ticker} indexed accessions: {', '.join(indexed_accessions)}")
    sources.append(f"{f.ticker} fundamentals: yfinance .info (point-in-time)")
    print(footer(source_lines=sources))


def _render_coverage(cov: Coverage, *, low_signal_deferred: bool = False) -> None:
    """Tell the reader what the eval rests on (issues #38, #40).

    Loud when the annual report is missing (the verdict would be thin); a quiet
    one-liner when the annual report is in but quarterly/proxy are still queued;
    plus a note disclosing when low-signal/administrative filings were deferred
    (the default `index` profile — see #40).
    """
    if not cov.eval_ready:
        print(
            "> **Partial coverage.** The annual report (10-K / 20-F) is not "
            f"indexed yet — this eval rests on {cov.indexed_count} lower-signal "
            f"filing(s) and may be thin. Run `clarion-sec-research index {cov.ticker}`, "
            "wait for the annual report to finish indexing, then evaluate again."
        )
        print()
        return
    gaps = cov.missing()
    if gaps:
        print(
            f"*Coverage: annual report (`{cov.core_form}`) indexed. Not yet indexed: "
            f"{', '.join(gaps)} — this eval reflects the annual report.*"
        )
        print()
    if low_signal_deferred:
        print(
            "*Administrative / registration filings (13G, S-8, 144, 424B, …) are not "
            f"indexed. For exhaustive diligence: `clarion-sec-research index {cov.ticker} "
            "--profile full`.*"
        )
        print()


def _render_market_context(snap: RegimeSnapshot) -> None:
    print("## Market context")
    print()
    print(f"Regime: **{snap.color.upper()}** — {snap.rationale}")
    if snap.hurdle_rate_pct is not None:
        print()
        print(
            show_math(
                "Equity hurdle",
                f"rf + {HURDLE_PREMIUM_PCT[snap.color]:.1f}% regime premium",
                f"{snap.hurdle_rate_pct:.2f}%",
            )
        )


def _render_quality_snapshot(f: Fundamentals) -> None:
    print("## Quality snapshot")
    print()
    print("*yfinance .info — point-in-time data; verify against the latest filing for serious decisions.*")
    print()
    rows = [
        ["Market cap", _fmt_money(f.market_cap)],
        ["Trailing P/E", _fmt_num(f.trailing_pe)],
        ["Forward P/E", _fmt_num(f.forward_pe)],
        ["Price/Book", _fmt_num(f.price_to_book)],
        ["Operating margin", _fmt_pct(f.operating_margin)],
        ["Profit margin", _fmt_pct(f.profit_margin)],
        ["Return on equity", _fmt_pct(f.return_on_equity)],
        ["Return on assets", _fmt_pct(f.return_on_assets)],
        ["Debt/Equity", _fmt_num(f.debt_to_equity)],
        ["Free cash flow (TTM)", _fmt_money(f.free_cash_flow)],
        ["Operating cash flow (TTM)", _fmt_money(f.operating_cash_flow)],
        ["Dividend yield", _fmt_pct(f.dividend_yield)],
        ["52w high", _fmt_money(f.week52_high)],
        ["52w low", _fmt_money(f.week52_low)],
        ["Last close", _fmt_money(f.last_close)],
    ]
    print(md_table(["Metric", "Value"], rows))


def _render_lens_view(lv: LensView) -> None:
    print(f"### {lv.title}")
    print()
    if not lv.hits:
        print(no_data(f"no hits in indexed filings for the {lv.dimension} query."))
        print()
        return
    for h in lv.hits:
        print(f"> {h.snippet}")
        print()
        print(f"— {h.citation}")
        print()


def _reading_guide(regime_snap: RegimeSnapshot | None) -> str:
    """Tells Zo what to do with the structured output. SKILL.md amplifies."""
    lines = [
        "Reason over the data above to produce a Buffett-style evaluation:",
        "",
        "1. **Moat durability** — does the business have a sustainable competitive advantage? Are the moat snippets specific (named customers, contracts, brand, IP, scale) or vague?",
        "2. **Management quality** — does management discuss capital allocation explicitly? Buybacks at attractive prices? Dividends? Reinvestment? Are they aligned and honest?",
        "3. **Financial trends** — are revenue and operating margins expanding, stable, or eroding? Is FCF healthy and growing, or propped up by working capital / asset sales?",
        "4. **Risk profile** — what's the most severe risk in the indexed filings? Is it tail (unlikely but ruinous) or recurring (drag on returns)? Is the company mitigating it?",
    ]
    if regime_snap is not None and regime_snap.hurdle_rate_pct is not None:
        lines.append(
            f"5. **Hurdle clearance** — does the expected return on this position clear "
            f"{regime_snap.hurdle_rate_pct:.1f}% (the {regime_snap.color.upper()} regime hurdle)?"
        )
    lines.append("")
    lines.append(
        "Show your math. Cite the filing on every claim drawn from filings — copy the canonical "
        "`citation` line under each snippet. End with one of three verdicts: **Add** / "
        "**Watchlist** / **Skip**."
    )
    return "\n".join(lines)


# ---- formatters -------------------------------------------------------------


def _fmt_money(v: float | None) -> str:
    if v is None:
        return "—"
    av = abs(v)
    if av >= 1e9:
        return f"${v/1e9:.2f}B"
    if av >= 1e6:
        return f"${v/1e6:.1f}M"
    return f"${v:,.2f}"


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v*100:.2f}%"


def _fmt_num(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:.2f}"


def main() -> int:
    ap = argparse.ArgumentParser(prog="clarion-single-stock-eval")
    ap.add_argument("ticker", type=str.upper)
    ap.add_argument(
        "--rf-rate-pct",
        type=float,
        default=None,
        help="1Y T-bill yield as a percent (e.g. 4.5). Adds equity hurdle to market context.",
    )
    ap.add_argument(
        "--no-regime",
        action="store_true",
        help="Skip regime/hurdle calculation (fundamentals + lens only).",
    )
    ap.add_argument(
        "--timing",
        action="store_true",
        help="Emit a per-stage timing summary to stderr (issue #42 — latency diagnostics).",
    )
    args = ap.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
