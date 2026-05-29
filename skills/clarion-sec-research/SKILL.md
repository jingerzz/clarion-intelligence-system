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

Five subcommands: `index`, `search`, `status`, `reindex`, `doctor`.

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
3. **If NOT indexed** → run `index <TICKER>` (no flags). This enqueues the **eval profile** (high-signal default): latest 2 10-Ks, latest 3 10-Qs, latest DEF 14A, 8-Ks and other high-signal forms from the last 90 days, plus the latest few insider Form 4s. Administrative/registration forms (S-8, 424B, 13G, …) are deferred — add `--profile full` for those when doing deep diligence. The queue is **priority-ordered** — the annual report (10-K / 20-F) indexes first, then quarterlies, then proxies — so a ticker becomes **eval-ready** well before the set finishes. Tell the user indexing is queued (typically 1-5 minutes per filing) and that they can re-run `status <TICKER>` to watch the **Eval readiness** line flip to "Ready to evaluate." For a narrow query, use `--form X` to scope the index to one form.
4. **If the user asks a thematic question across multiple tickers** (e.g. "which of NVDA, AMD, INTC mentions supply chain risk?"), run `search` with `--tickers NVDA,AMD,INTC`. If any of the tickers shows zero hits, surface that and suggest indexing them.

## How to run

The script is at `/home/workspace/clarion-intelligence-system/skills/clarion-sec-research/scripts/research.py`. Below, `RESEARCH=python /home/workspace/clarion-intelligence-system/skills/clarion-sec-research/scripts/research.py` for brevity.

### Index

```bash
# Composite default — EVAL profile (high-signal set for a first-pass evaluation):
#   latest 2 10-Ks + latest 3 10-Qs + latest DEF 14A + 8-K & other high-signal
#   forms in the last 90 days + the latest few insider Form 4s (deduped).
# Administrative/registration forms (13G/D, S-8, 144, 424B, EFFECT, ARS) are deferred.
$RESEARCH index NVDA

# FULL profile — everything above PLUS all remaining forms in the last 90 days
# (administrative/registration). Use when moving toward sizing or publication.
$RESEARCH index NVDA --profile full

# Form-scoped — ALL filings of FORM in the window (default 90 days), any profile:
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

`--form` accepts any SEC form name. Pass it exactly as SEC reports it (e.g. `10-K`, `10-Q`, `4`, `3`, `5`, `8-K`, `S-1`, `DEF 14A`, `20-F`). Amendments use `/A` suffix (`10-K/A`). `--latest` is mutually exclusive with `--days`/`--count`. `--profile` applies only to the composite default (it's ignored with `--form`).

**Why two profiles (issue #40):** a Buffett-lens evaluation runs on year-over-year financials (10-Ks), recent operating context (10-Qs), governance/comp (DEF 14A), material events (8-K), and a little insider signal (recent Form 4s) — which is exactly the **eval** profile. Pulling *every* administrative/registration filing from the last 90 days (S-8, 424B, 13G, …) adds indexing time without changing a first-pass view, so it's deferred to **`--profile full`** for deep diligence. `clarion-single-stock-eval` discloses in its output when administrative filings weren't indexed.

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

### Reindex

```bash
$RESEARCH reindex            # whole corpus: re-extract anything built by older code
$RESEARCH reindex NVDA       # just one ticker
$RESEARCH reindex --force    # re-extract everything, even if already current
```

Re-extracts already-indexed filings so the latest extraction fixes reach your existing corpus (issue #57). By default it only re-extracts filings built by **older code** — filings already on the current code are skipped, so it's safe and cheap to re-run. **This is the command to run after upgrading** (after `doctor` confirms the service is current). Without it, an upgrade only affects newly-indexed filings; your existing data keeps its old extraction.

### Doctor

```bash
$RESEARCH doctor
```

Checks whether the running `sec-indexer` service is on the **currently installed** code (issue #55). After pulling code updates, the long-running service must be restarted or it keeps executing old code and re-indexing produces wrong data — silently. Run `doctor` after any update (and before a big re-index); if it reports `STALE`, restart the service, then `reindex`. Exit code is non-zero on STALE.

## Output

Each subcommand prints structured markdown that you should pass through to the user verbatim. `index` confirms the queue submission. `search` returns a hit table and top-5 snippets with citations. `status` shows an **Eval readiness** summary (whether the annual report is indexed yet, plus any high-signal gaps), the indexed filings, and last request state. `reindex` confirms which filings were queued for re-extraction. `doctor` reports indexer code freshness (up to date / STALE / not started).

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
