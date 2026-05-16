# DuckDB Portfolio History Schema

## Purpose

Auditable daily portfolio history — one row per position per day, plus a daily portfolio summary. Designed so anyone can verify performance claims against real trade data.

## Location

`~/clarion/portfolio/portfolio.duckdb` — a single-file database next to the daily JSON snapshots.

## Tables

### portfolio_daily

One row per account per day. Portfolio-level summary.

| Column | Type | Description |
|---|---|---|
| `date` | DATE | Snapshot date (PK) |
| `account_number` | VARCHAR | TastyTrade account number (PK) |
| `nlv` | DOUBLE | Net Liquidating Value |
| `cash_balance` | DOUBLE | Uninvested cash |
| `equity_buying_power` | DOUBLE | Available buying power |
| `margin_equity` | DOUBLE | Total equity in margin account |
| `maintenance_excess` | DOUBLE | Headroom above maintenance margin |
| `position_count` | INTEGER | Number of open positions |
| `daily_pl` | DOUBLE | Total P/L today (unrealized + realized) |
| `daily_pl_unrealized` | DOUBLE | Unrealized P/L today |
| `daily_pl_realized` | DOUBLE | Realized P/L today |
| `fetched_at` | TIMESTAMP | When the snapshot was fetched |

### position_daily

One row per position per day. The audit trail.

| Column | Type | Description |
|---|---|---|
| `date` | DATE | Snapshot date (PK) |
| `account_number` | VARCHAR | Account (PK) |
| `symbol` | VARCHAR | Ticker symbol (PK) |
| `instrument_type` | VARCHAR | "Equity", "Option", etc. |
| `direction` | VARCHAR | "Long" or "Short" |
| `quantity` | DOUBLE | Shares held |
| `mark_price` | DOUBLE | Mark price at snapshot time |
| `cost_basis` | DOUBLE | Average cost per share |
| `multiplier` | DOUBLE | Contract multiplier (1 for equities) |
| `unrealized_pl` | DOUBLE | Unrealized P/L at mark |
| `unrealized_pl_pct` | DOUBLE | P/L as percentage |
| `realized_day_pl` | DOUBLE | Realized P/L for the day |

## Why row-based, not column-based

Each position is a row keyed by `(date, symbol)`. New positions appear naturally as new rows — no schema migration needed when the portfolio changes. Every day's snapshot adds one row per open position plus one portfolio-level row.

## How to audit

```sql
-- Full history: every position, every day
SELECT * FROM position_daily ORDER BY date, symbol;

-- NLV over time (simple performance report)
SELECT date, nlv FROM portfolio_daily ORDER BY date;

-- Track a single position from entry
SELECT date, mark_price, cost_basis, unrealized_pl
FROM position_daily
WHERE symbol = 'IREN'
ORDER BY date;
```

Or use `python scripts/query.py audit` for a full CSV dump.

## Idempotency

`INSERT OR REPLACE` — re-loading the same date overwrites rows, never duplicates. Every date is a point-in-time record; backfilling from old JSONs is safe.
