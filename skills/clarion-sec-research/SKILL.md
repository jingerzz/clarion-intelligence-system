---
name: clarion-sec-research
description: Pull, index, and search SEC EDGAR filings for any public company. Supports 10-K and 10-Q (annual/quarterly with curated section extraction for risk factors, MD&A, business, and financials), Form 3/4/5 (insider transactions), 8-K (material events), DEF 14A (proxy/governance), S-1 (IPO/registration), 20-F (foreign private issuers), and any other SEC form by name. Use when the user asks about a company's SEC filings, risk factors, MD&A, insider transactions, executive compensation, business description, or wants to analyze a specific filing in plain English. Single ticker or multiple tickers (comma-separated). On first request for a ticker+form, indexing happens in the background (1-5 min). Subsequent queries are fast. Requires clarion-setup to have been run.
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
- "Has there been any insider activity at NVDA?" (Form 4)
- "Pull NVDA's latest insider transaction report." (Form 4)
- "What's in TSLA's most recent 8-K?"
- "Show me META's proxy statement on executive compensation." (DEF 14A)
- "Index AMD."

## Decision tree

When the user asks about a specific ticker:

1. Run `status <TICKER>` to check whether the requested filings are already indexed.
2. **If indexed** → run `search` with a query phrase that captures the user's question. Pass `--tickers <TICKER>` to scope the search.
3. **If NOT indexed** → run `index <TICKER>` (no flags). This enqueues the **composite default set**: the latest 2 10-Ks, latest 3 10-Qs, and **all filings in the last 90 days** (Form 4, 8-K, etc.). The queue is **priority-ordered** — the annual report (10-K / 20-F) indexes first, then quarterlies, then proxies, then low-signal forms — so a ticker becomes **eval-ready** (annual report done) well before the whole set finishes. Tell the user indexing is queued (typically 1-5 minutes per filing) and that they can re-run `status <TICKER>` to watch the **Eval readiness** line flip to "Ready to evaluate." For a narrow query, use `--form X` to scope the index to one form.
4. **If the user asks a thematic question across multiple tickers** (e.g. "which of NVDA, AMD, INTC mentions supply chain risk?"), run `search` with `--tickers NVDA,AMD,INTC`. If any of the tickers shows zero hits, surface that and suggest indexing them.

## How to run

The script is at `/home/workspace/clarion-intelligence-system/skills/clarion-sec-research/scripts/research.py`. Below, `RESEARCH=python /home/workspace/clarion-intelligence-system/skills/clarion-sec-research/scripts/research.py` for brevity.

### Index

```bash
# Composite default — eval-ready set:
#   latest 2 10-Ks + latest 3 10-Qs + ALL filings in the last 90 days
# (deduped by accession). Use this when preparing a ticker for `clarion-single-stock-eval`.
$RESEARCH index NVDA

# Form-scoped — ALL filings of FORM in the window (default 90 days):
$RESEARCH index NVDA --form 4              # all Form 4s (insider transactions) in last 90d
$RESEARCH index TSLA --form 8-K            # all 8-Ks in last 90d
$RESEARCH index META --form "DEF 14A"      # all proxy statements in last 90d
$RESEARCH index BABA --form 20-F           # all 20-Fs in last 90d

# Tune the window:
$RESEARCH index NVDA --form 4 --days 180   # all Form 4s in last 180d
$RESEARCH index NVDA --form 10-K --count 3 # most-recent 3 10-Ks (any age)

# Legacy single-result — only the single most-recent filing of FORM:
$RESEARCH index NVDA --form 10-Q --latest  # just the latest 10-Q
```

`--form` accepts any SEC form name. Pass it exactly as SEC reports it (e.g. `10-K`, `10-Q`, `4`, `3`, `5`, `8-K`, `S-1`, `DEF 14A`, `20-F`). Amendments use `/A` suffix (`10-K/A`). `--latest` is mutually exclusive with `--days`/`--count`.

**Why the default fans out:** a Buffett-lens evaluation needs year-over-year financials (multiple 10-Ks), recent operating context (multiple 10-Qs), and insider/material activity (Form 4s, 8-Ks) from the last quarter. A single 10-K starves the Management & capital-allocation dimension of `clarion-single-stock-eval`. The composite default makes one `index` call enough to support a complete eval.

### Search

```bash
$RESEARCH search "supply chain risk"
$RESEARCH search "supply chain risk" --tickers NVDA,AMD
$RESEARCH search "competitive pressure" --sections risk_factors,mdna
$RESEARCH search "data center revenue" --top-k 5
$RESEARCH search "insider transaction" --tickers NVDA  # Form 4 hits
```

**Section labels** depend on the form type:

- **10-K / 10-Q** use canonical labels (curated extraction): `business`, `risk_factors`, `mdna`, `financial_statements`. The `--sections` filter is most useful here.
- **All other forms** (Form 4, 8-K, S-1, DEF 14A, etc.) use slugified labels derived from each filing's headings — e.g. Form 4 sections appear as `form-4-insider-transaction-report`, `issuer`, `reporting-owners`, `non-derivative-transactions`. Look at `status` output or run `search` without `--sections` to see what's actually indexed before filtering.

### Status

```bash
$RESEARCH status NVDA
```

## Output

Each subcommand prints structured markdown that you should pass through to the user verbatim. `index` confirms the queue submission. `search` returns a hit table and top-5 snippets with citations. `status` shows an **Eval readiness** summary (whether the annual report is indexed yet, plus any high-signal gaps), the indexed filings, and last request state.

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
