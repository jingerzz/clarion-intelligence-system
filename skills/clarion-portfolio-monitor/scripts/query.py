#!/usr/bin/env python3
"""
Clarion Portfolio Monitor — DuckDB query tool.

Run ad-hoc queries and common reports against portfolio history.

Usage:
    python query.py nlv              # NLV over time (csv)
    python query.py positions        # Latest positions
    python query.py position SYM     # Single position history
    python query.py pnl              # Cumulative P/L by symbol
    python query.py summary          # Portfolio summary (latest date)
    python query.py audit            # Full audit trail (all data)
    python query.py --sql "SELECT ..."  # Raw SQL query
"""

import argparse
import os
import sys
from pathlib import Path
import duckdb

CLARION_DATA_ROOT = os.environ.get("CLARION_DATA_ROOT", "/home/workspace/clarion")
DB_PATH = Path(CLARION_DATA_ROOT) / "portfolio" / "portfolio.duckdb"

QUERIES = {
    "nlv": """
        SELECT date, nlv, cash_balance, daily_pl
        FROM portfolio_daily
        ORDER BY date
    """,
    "positions": """
        WITH latest AS (
            SELECT MAX(date) as max_date FROM position_daily
        )
        SELECT symbol, direction, quantity,
               ROUND(mark_price, 2) as mark,
               ROUND(cost_basis, 2) as cost_basis,
               ROUND(unrealized_pl, 2) as unrealized_pl,
               ROUND(unrealized_pl_pct, 2) as pl_pct,
               ROUND(quantity * mark_price, 2) as market_value
        FROM position_daily, latest
        WHERE date = max_date
        ORDER BY market_value DESC
    """,
    "pnl": """
        WITH latest AS (
            SELECT MAX(date) as max_date FROM position_daily
        )
        SELECT symbol, direction,
               ROUND(unrealized_pl, 2) as unrealized_pl,
               ROUND(unrealized_pl_pct, 2) as pct,
               ROUND(quantity * mark_price, 2) as market_value
        FROM position_daily, latest
        WHERE date = max_date
        ORDER BY unrealized_pl DESC
    """,
    "summary": """
        WITH latest AS (
            SELECT MAX(date) as max_date FROM portfolio_daily
        )
        SELECT p.date, p.nlv, p.cash_balance, p.equity_buying_power,
               p.position_count, p.daily_pl, p.daily_pl_unrealized,
               p.daily_pl_realized,
               (SELECT COUNT(*) FROM position_daily WHERE date = p.date) as total_positions
        FROM portfolio_daily p, latest
        WHERE p.date = latest.max_date
    """,
    "audit": """
        -- Full history of every position, every day
        SELECT pd.date, pd.symbol, pd.direction, pd.quantity,
               ROUND(pd.mark_price, 2) as mark,
               ROUND(pd.cost_basis, 2) as cost_basis,
               ROUND(pd.unrealized_pl, 2) as unrealized_pl,
               p.nlv
        FROM position_daily pd
        JOIN portfolio_daily p ON pd.date = p.date AND pd.account_number = p.account_number
        ORDER BY pd.date DESC, pd.symbol
    """,
}


def main():
    parser = argparse.ArgumentParser(description="Query portfolio history from DuckDB")
    parser.add_argument("report", nargs="?", default="summary",
                        choices=list(QUERIES.keys()) + ["position"],
                        help="Report to run")
    parser.add_argument("--symbol", "-s", type=str, help="Symbol for position report")
    parser.add_argument("--sql", type=str, help="Raw SQL query")
    parser.add_argument("--days", type=int, default=30, help="Days of history (for NLV)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        print("Run load.py first to populate the database.")
        sys.exit(1)

    con = duckdb.connect(str(DB_PATH), read_only=True)

    if args.sql:
        try:
            result = con.execute(args.sql)
            print(result.fetch_df().to_string(index=False))
        except Exception as e:
            print(f"SQL error: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            con.close()
        return

    if args.report == "position":
        if not args.symbol:
            print("Use --symbol SYM to query a specific position")
            sys.exit(1)
        sql = """
            SELECT date, direction, quantity,
                   ROUND(mark_price, 2) as mark,
                   ROUND(cost_basis, 2) as cost_basis,
                   ROUND(unrealized_pl, 2) as unrealized_pl,
                   ROUND(unrealized_pl_pct, 2) as pl_pct
            FROM position_daily
            WHERE symbol = ?
            ORDER BY date
        """
        df = con.execute(sql, [args.symbol.upper()]).fetch_df()
    elif args.report == "nlv":
        days = args.days
        df = con.execute(f"""
            SELECT date, ROUND(nlv, 2) as nlv,
                   ROUND(cash_balance, 2) as cash,
                   ROUND(daily_pl, 2) as daily_pl,
                   position_count
            FROM portfolio_daily
            ORDER BY date DESC
            LIMIT {days}
        """).fetch_df()
    else:
        sql = QUERIES[args.report]
        df = con.execute(sql).fetch_df()

    print(df.to_string(index=False))
    con.close()


if __name__ == "__main__":
    main()
