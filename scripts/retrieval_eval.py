#!/usr/bin/env python3
"""retrieval_eval.py — gold-set regression harness for secrag search quality.

Runs a set of gold queries against the indexed corpus and scores whether the
expected section labels surface in the top-K hits. This is the regression
gate for retrieval changes (BM25F, doc2query, RRF, extraction fixes): run it
before and after, compare hit rates.

Gold file format (JSON):
    [
      {
        "query": "how much cash does the company have",
        "ticker": "DBX",
        "expected_labels": ["financials", "mdna"],   # hit if ANY appears in top-K
        "note": "optional human note"
      },
      ...
    ]

Usage:
    python scripts/retrieval_eval.py eval/retrieval-gold.json
    python scripts/retrieval_eval.py eval/retrieval-gold.json --top-k 5
    python scripts/retrieval_eval.py eval/retrieval-gold.json --reasoning
    python scripts/retrieval_eval.py eval/retrieval-gold.json --json out.json

By default runs Stage 1 only (reasoning=False): deterministic, free, fast —
the right baseline for regression comparison. --reasoning enables the full
weak-path pipeline (LLM rewrite + tree navigation + RRF); requires ZO_API_KEY
or an active agent turn.

Exit code: 0 always when the run completes (this is a measurement tool, not
a pass/fail gate — compare hit rates across runs). Non-zero on setup errors.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from ai_buffett_zo.secrag import DEFAULT_SEC_ROOT, search


def run(args: argparse.Namespace) -> int:
    gold_path = Path(args.gold_file)
    if not gold_path.exists():
        print(f"ERROR: gold file not found: {gold_path}", file=sys.stderr)
        return 2
    gold = json.loads(gold_path.read_text())
    if not isinstance(gold, list) or not gold:
        print("ERROR: gold file must be a non-empty JSON array", file=sys.stderr)
        return 2

    root = Path(args.root).expanduser()
    results = []
    hits_at_k = 0
    mrr_total = 0.0

    for i, item in enumerate(gold):
        query = item["query"]
        ticker = item.get("ticker")
        expected = set(item.get("expected_labels", []))
        if not expected:
            print(f"WARN: gold item {i} has no expected_labels; skipping")
            continue

        hits = search(
            query,
            root=root,
            tickers=[ticker] if ticker else None,
            top_k=args.top_k,
            reasoning=args.reasoning,
        )
        got_labels = [h.section_label for h in hits]
        rank = next(
            (r for r, label in enumerate(got_labels) if label in expected), None
        )
        hit = rank is not None
        hits_at_k += int(hit)
        mrr_total += 1.0 / (rank + 1) if hit else 0.0

        results.append(
            {
                "query": query,
                "ticker": ticker,
                "expected_labels": sorted(expected),
                "got_labels": got_labels,
                "hit": hit,
                "rank": rank,
                "top_score": hits[0].score if hits else None,
            }
        )
        marker = "✓" if hit else "✗"
        rank_str = f"rank {rank}" if hit else "MISS"
        print(f"{marker} [{ticker or 'ALL'}] {query!r} → {rank_str}  (top: {got_labels[:3]})")

    n = len(results)
    if n == 0:
        print("ERROR: no scorable gold items", file=sys.stderr)
        return 2

    summary = {
        "ran_at": datetime.now(UTC).isoformat(),
        "gold_file": str(gold_path),
        "top_k": args.top_k,
        "reasoning": args.reasoning,
        "n_queries": n,
        "hit_rate": round(hits_at_k / n, 4),
        "mrr": round(mrr_total / n, 4),
        "results": results,
    }

    print()
    print(f"hit@{args.top_k}: {hits_at_k}/{n} = {summary['hit_rate']:.1%}   MRR: {summary['mrr']:.3f}")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=2))
        print(f"wrote {out}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("gold_file", help="path to gold-set JSON")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--root", default=str(DEFAULT_SEC_ROOT), help="indexed corpus root")
    p.add_argument("--reasoning", action="store_true", help="enable weak-path LLM pipeline")
    p.add_argument("--json", help="write full results JSON here")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
