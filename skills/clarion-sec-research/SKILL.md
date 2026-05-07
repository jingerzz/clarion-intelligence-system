---
name: clarion-sec-research
description: Pull, index, and search SEC EDGAR filings (10-K, 10-Q). Use when the user asks about a company's SEC filings, risk factors, MD&A, business description, or wants to analyze a specific filing in plain English. Single ticker or multiple tickers (comma-separated). On first request for a ticker, indexing happens in the background (1-5 min). Subsequent queries are fast. Requires clarion-setup to have been run.
metadata:
  author: cis.zo.computer
  category: External
  display-name: Clarion SEC Research
  homepage: https://github.com/jingerzz/clarion-intelligence-system
---

# Clarion SEC research

Three subcommands: `index`, `search`, `status`.

## When to use

User asks any of:
- "Analyze NVDA's most recent 10-K."
- "What are the risk factors for AAPL?"
- "Compare KO's MD&A across the last two 10-Ks."
- "Pull NVDA's latest 10-Q."
- "What does NVDA say about supply chain?"
- "Index AMD."

## Decision tree

When the user asks about a specific ticker:

1. Run `status <TICKER>` to check whether the requested filing is already indexed.
2. **If indexed** → run `search` with a query phrase that captures the user's question. Pass `--tickers <TICKER>` to scope the search.
3. **If NOT indexed** → run `index <TICKER> [--form 10-Q]`. Tell the user the indexing is queued (typically 1-5 minutes) and suggest they come back.
4. **If the user asks a thematic question across multiple tickers** (e.g. "which of NVDA, AMD, INTC mentions supply chain risk?"), run `search` with `--tickers NVDA,AMD,INTC`. If any of the tickers shows zero hits, surface that and suggest indexing them.

## How to run

The script is at `/home/workspace/clarion-intelligence-system/skills/clarion-sec-research/scripts/research.py`. Below, `RESEARCH=python /home/workspace/clarion-intelligence-system/skills/clarion-sec-research/scripts/research.py` for brevity.

### Index

```bash
$RESEARCH index NVDA              # latest 10-K (default)
$RESEARCH index NVDA --form 10-Q  # latest 10-Q
```

### Search

```bash
$RESEARCH search "supply chain risk"
$RESEARCH search "supply chain risk" --tickers NVDA,AMD
$RESEARCH search "competitive pressure" --sections risk_factors,mdna
$RESEARCH search "data center revenue" --top-k 5
```

Section labels: `business`, `risk_factors`, `mdna`, `financial_statements`.

### Status

```bash
$RESEARCH status NVDA
```

## Output

Each subcommand prints structured markdown that you should pass through to the user verbatim. `index` confirms the queue submission. `search` returns a hit table and top-5 snippets with citations. `status` lists indexed filings and last request state.

When you want to **summarize or interpret** the filing content beyond the script's snippets:

- Quote specific numbers from the filing where relevant.
- **Always cite** the filing on each claim. The search output's `citation` field is the canonical form: `NVDA 10-K filed 2026-02-21 → risk_factors`.
- Tier 1 is the filing itself. Don't speculate beyond what's in the text.
- If the user asks a question and the answer isn't in the indexed corpus, say so explicitly — don't fill in from training data.

## Voice

Conservative and direct. Show the math (numbers from the filing) where relevant. Never fabricate financial data — if the search snippet doesn't have the number the user asked for, say "the indexed sections don't contain that figure" and offer to index more sections or another form (e.g. the 10-Q for more recent data).

## On error

- **`status` shows last_request.state = failed`** — the indexer hit an error. Surface the `error` field. Common causes: ticker not in SEC's tickers map (typo), no `ZO_API_KEY` set, network issue.
- **`search` returns no hits** for a ticker that should have content — confirm with `status` that indexing actually completed; if `state` is still `running` or missing, indexing isn't done yet.
