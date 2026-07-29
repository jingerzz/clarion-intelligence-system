---
name: clarion-portfolio-monitor
description: Fetch live portfolio positions, balances, and daily transactions from TastyTrade. Outputs a structured JSON snapshot and a human-readable summary to ~/clarion/portfolio/. Use when the user asks for portfolio status, net liquidation value (NLV), position P/L, daily fills, or needs current holdings for the investor letter or thesis monitoring. Requires TastyTrade OAuth credentials (client secret + refresh token) stored as Zo secrets.
compatibility: Created for Zo Computer
metadata:
  author: cis.zo.computer
  category: External
  display-name: Clarion Portfolio Monitor
  homepage: https://github.com/jingerzz/clarion-intelligence-system
---

# Clarion Portfolio Monitor

Fetches live portfolio data from TastyTrade (balances, positions, P/L, daily transactions)
Stores every snapshot in DuckDB for auditable performance history (cost basis, mark price, NLV per position per day)
Integration points: Portfolio Manager (live data + cost basis), LP Voice (performance claims for investor letter)

Runs as a on-demand script — no network exposure, no persistent MCP server. Reads credentials from Zo secrets, authenticates with a refresh token (never expires), and writes a timestamped snapshot.

## What it fetches

- **Account balances**: net liquidating value (NLV), cash balance, buying power, margin equity
- **Open positions**: symbol, quantity, direction, mark price, cost basis, unrealized P/L, realized day P/L
- **Today's transactions**: fills (buys + sells), dividends, cash events
- **NLV history**: trailing 30-day NLV for trend context

## Output

| File | Format | Purpose |
|---|---|---|
| `~/clarion/portfolio/YYYY-MM-DD.json` | JSON, full raw data | Machine-readable, ingested by investor letter tooling |
| `~/clarion/portfolio/YYYY-MM-DD.md` | Markdown summary | Human-readable, surfaced in chat |
| `~/clarion/portfolio/latest.json` | Symlink to today's JSON | Quick "what's current" access |

## Prerequisites

1. A TastyTrade OAuth application created at https://my.tastytrade.com/app.html#/manage/api-access/oauth-applications
2. A refresh token generated via OAuth Applications > Manage > Create Grant
3. Both stored as Zo secrets in [Settings > Advanced](/?t=settings&s=advanced):
   - `TASTYTRADE_CLIENT_SECRET` — the OAuth app client secret
   - `TASTYTRADE_REFRESH_TOKEN` — the generated refresh token

Refresh tokens never expire. One-time setup.

## Usage

```
python /home/workspace/Skills/clarion-portfolio-monitor/scripts/fetch.py
```

Options:
- `--json-only` — skip markdown summary, produce only JSON
- `--account N` — specify account number (auto-detects if omitted)
- `--no-history` — skip NLV history fetch (faster)

## Trade ledger (cost-basis verification)

`scripts/trade-ledger.py` maintains a `transactions` table in
`~/clarion/portfolio/portfolio.duckdb`, backfilled from TastyTrade full account
history and upserted idempotently by transaction ID. It derives per-symbol cost
basis and realized P/L from fills via FIFO lot replay, and reconciles against
the broker snapshot and thesis YAML.

```
python trade-ledger.py sync [--days N] [--full]   # fetch + upsert transactions
python trade-ledger.py positions                  # derived positions from ledger
python trade-ledger.py lots [--markdown] [--json] # open lots per position
python trade-ledger.py verify                     # ledger vs broker vs thesis YAML
python trade-ledger.py realized                   # realized P/L by symbol
```

- First sync (or `--full`) backfills from `CLARION_LEDGER_INCEPTION`
  (env var, ISO date, default `2000-01-01` — set it to your account's
  inception to keep backfills fast). Subsequent syncs default to the last 7 days.
- `fetch.py` automatically appends open-lot detail to the markdown summary
  when the ledger is available; it degrades gracefully when it isn't.
- Uses the same TastyTrade secrets as `fetch.py`. `verify` and `positions`
  are offline (no API call).

## Scheduling

For daily snapshots, create a Zo Automation:
- Rrule: `FREQ=DAILY;BYHOUR=17;BYMINUTE=30` (after market close Eastern)
- Instruction: `Run python /home/workspace/Skills/clarion-portfolio-monitor/scripts/fetch.py and report any positions with >5% daily move.`

## Integrating with other Clarion skills

- **Clarion LP Voice** (`clarion-living-letter-update`): reads `~/clarion/portfolio/latest.json` for the "What We Did" section and NLV context
- **Clarion Portfolio Manager** (`clarion-thesis-monitor`): compares live positions against active theses to detect thesis drift
- **Clarion Macro Sentinel** (`clarion-regime-check`): not directly integrated — portfolio data is downstream of regime decisions
