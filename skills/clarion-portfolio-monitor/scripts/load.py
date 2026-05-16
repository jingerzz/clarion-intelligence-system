#!/usr/bin/env python3
"""
Clarion Portfolio Monitor — DuckDB loader.

Reads a daily JSON snapshot from ~/clarion/portfolio/YYYY-MM-DD.json
(or the latest.json symlink) and upserts into portfolio_daily and
position_daily tables in portfolio.duckdb.

Usage:
    python load.py                          # load latest.json
    python load.py --date 2026-05-15        # load specific date
    python load.py --json path/to/file.json # load arbitrary snapshot
    python load.py --history                # backfill all available JSONs

The loader is idempotent — re-running on the same date replaces the row,
not duplicates it.
"""

import argparse
import json
import os
from datetime import date, datetime
from pathlib import Path
import duckdb

CLARION_DATA_ROOT = os.environ.get("CLARION_DATA_ROOT", "/home/workspace/clarion")
PORTFOLIO_DIR = Path(CLARION_DATA_ROOT) / "portfolio"
DB_PATH = PORTFOLIO_DIR / "portfolio.duckdb"


def load_snapshot(snapshot_path: Path, con: duckdb.DuckDBPyConnection) -> dict:
    """Load one snapshot JSON into DuckDB. Returns {records: N, date: str}."""
    with open(snapshot_path) as f:
        data = json.load(f)

    fetched_at = data.get("fetched_at")
    snapshot_date = fetched_at[:10] if fetched_at else data.get("date", str(date.today()))

    stats = {"records": 0, "date": snapshot_date}

    for account in data.get("accounts", []):
        acct_num = account["account_number"]
        balances = account.get("balances", {})

        # Compute daily P/L from positions or from balances
        positions = account.get("positions", [])
        pos_count = len(positions)
        unrealized_pl = sum(p.get("unrealized_pl", 0) or 0 for p in positions)
        realized_pl = sum(p.get("realized_day_pl", 0) or 0 for p in positions)

        # Upsert portfolio_daily
        con.execute("""
            INSERT OR REPLACE INTO portfolio_daily
            (date, account_number, nlv, cash_balance, equity_buying_power,
             margin_equity, maintenance_excess, position_count,
             daily_pl, daily_pl_unrealized, daily_pl_realized, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            snapshot_date,
            acct_num,
            balances.get("net_liquidating_value", 0),
            balances.get("cash_balance", 0),
            balances.get("equity_buying_power", 0),
            balances.get("margin_equity", 0),
            balances.get("maintenance_excess", 0),
            pos_count,
            unrealized_pl + realized_pl,
            unrealized_pl,
            realized_pl,
            fetched_at,
        ])

        # Upsert position_daily
        for pos in positions:
            con.execute("""
                INSERT OR REPLACE INTO position_daily
                (date, account_number, symbol, instrument_type, direction,
                 quantity, mark_price, cost_basis, multiplier,
                 unrealized_pl, unrealized_pl_pct, realized_day_pl)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                snapshot_date,
                acct_num,
                pos.get("symbol", "???"),
                pos.get("instrument_type", "Equity"),
                pos.get("direction", "Long"),
                pos.get("quantity", 0),
                pos.get("mark_price", 0),
                pos.get("cost_basis", 0),
                pos.get("multiplier", 1),
                pos.get("unrealized_pl", 0) or 0,
                pos.get("unrealized_pl_pct", 0) or 0,
                pos.get("realized_day_pl", 0) or 0,
            ])
            stats["records"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Load portfolio snapshots into DuckDB")
    parser.add_argument("--date", type=str, help="Date to load (YYYY-MM-DD)")
    parser.add_argument("--json", type=str, help="Path to specific JSON file")
    parser.add_argument("--history", action="store_true", help="Backfill all available JSONs")
    args = parser.parse_args()

    con = duckdb.connect(str(DB_PATH))

    if args.history:
        # Load all JSON files in portfolio directory
        json_files = sorted(PORTFOLIO_DIR.glob("????-??-??.json"))
        if not json_files:
            print("No daily snapshots found in", PORTFOLIO_DIR)
            con.close()
            return

        total = 0
        for jf in json_files:
            stats = load_snapshot(jf, con)
            total += stats["records"]
            print(f"  {stats['date']}: {stats['records']} positions")

        print(f"\nTotal: {total} position records across {len(json_files)} dates")
    else:
        if args.json:
            json_path = Path(args.json)
        elif args.date:
            json_path = PORTFOLIO_DIR / f"{args.date}.json"
        else:
            # Use latest symlink or most recent file
            latest = PORTFOLIO_DIR / "latest.json"
            if latest.exists():
                json_path = latest.resolve()
            else:
                json_files = sorted(PORTFOLIO_DIR.glob("????-??-??.json"))
                if not json_files:
                    print("No snapshot found. Run fetch.py first.")
                    con.close()
                    sys.exit(1)
                json_path = json_files[-1]

        if not json_path.exists():
            print(f"Snapshot not found: {json_path}")
            con.close()
            sys.exit(1)

        stats = load_snapshot(json_path, con)
        print(f"Loaded {stats['date']}: {stats['records']} positions")

    con.close()
    print(f"Database: {DB_PATH}")


if __name__ == "__main__":
    import sys
    main()
