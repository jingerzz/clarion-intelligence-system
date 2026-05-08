# Clarion Intelligence System — Test Plan

A progressive stress test for a fresh Zo Computer install. Three tiers:

- **Tier 1** (~10 min) — smoke test: install, service, simplest end-to-end query.
- **Tier 2** (~30 min) — functional coverage: every skill exercised once + cross-skill composition.
- **Tier 3** (~as needed) — stress and regression: edge cases, error paths, previously-fixed bugs.

Run on a **fresh Zo workspace** for the strongest signal. If the system is already installed, skip Tier 1 and start at Tier 2.

For each test, record: Pass / Fail / Skipped + a one-line output excerpt or error if Failed. Bundle results into one chat message at the end.

## Tier 1 — Smoke test

**Goal:** prove the system installs, the service runs, and the simplest end-to-end query works.

### T1.1 — Install bootstrap skill

**Prompt:** `install the clarion-setup skill`

**Pass:** Zo confirms install.

### T1.2 — Run setup

**Prompt:** `set up Clarion`

**Pass:** Zo invokes `clarion-setup`. Clones the source repo into `/home/workspace/clarion-intelligence-system`, installs the lib, creates the workspace tree, then pauses to ask for the `ZO_API_KEY` secret.

### T1.3 — Create the `ZO_API_KEY` secret

Follow the prompt:

1. Settings → Advanced → Access Tokens → create a new token (any name). Copy the value.
2. Settings → Advanced → Secrets → create a secret named **exactly** `ZO_API_KEY` with the token as the value.
3. Tell Zo "done".

**Pass:** Zo calls `register_user_service`, reports a service ID, and prints `SETUP_RESULT: ok`.

### T1.4 — Verify the workspace

**Prompt:** `ls ~/clarion`

**Pass:** Subdirs `data/equities`, `sec`, `queue`, `theses`, `watchlists`, `letters`, plus `config.json`.

### T1.5 — Regime check (no SEC indexing required)

**Prompts:**

1. `install the clarion-regime-check skill`
2. `what's the market regime?`

**Pass:** Returns SPY/TLT/RSP color and the equity hurdle rate. Fast (no indexing). Proves the chat-skill auto-token path works without `ZO_API_KEY` in scope (chat skills get `ZO_CLIENT_IDENTITY_TOKEN` auto-injected; only the `sec-indexer` service needs `ZO_API_KEY`).

### T1.6 — SEC research happy path

**Prompts:**

1. `install the clarion-sec-research skill`
2. `index NVDA's latest 10-K`
3. *(wait 1-5 min)* `status NVDA`
4. *(once `status` shows completed)* `what does NVDA say about Blackwell?`

**Pass:** Indexing completes. Search returns a hit table + top-5 snippets. Every snippet has a canonical citation: `NVDA 10-K filed YYYY-MM-DD → section`.

**Tier 1 passes if T1.1-T1.6 all worked without intervention beyond the `ZO_API_KEY` creation step.**

## Tier 2 — Full functional coverage

**Goal:** exercise every skill at least once and prove cross-skill composition works.

### T2.1 — Multi-form indexing (regression test for the May 8 SEC-RAG fixes)

**Prompts:**

1. `index NVDA's latest Form 4`
2. `index TSLA's latest 8-K`
3. *(after both `status` show completed)* `has there been any insider activity at NVDA?`
4. `what happened in TSLA's most recent 8-K?`

**Pass:** Form 4 fetch returns XML (not the XSLT-rendered HTML). Search for "insider activity" returns hits in the `form-4-insider-transaction-report` section.

**This is the explicit regression test for two bugs caught during initial deployment:** the XSLT-prefix path on SEC EDGAR's `primaryDocument` field for ownership filings, and the Form 4 keyword-visibility issue (Form 4 XML doesn't contain the word "insider" in its body, so keyword search needed the heading enriched).

### T2.2 — Single-stock evaluation

**Prompt:** `evaluate NVDA`

**Pass:** Skill pulls quality table from yfinance, current SPY/TLT regime context, and snippets across four dimensions (moat, management, financial trends, risks). Zo synthesizes an Add / Watchlist / Skip verdict with citations on every filing-derived claim.

### T2.3 — Expected return calc

**Prompt:** `what's the equity hurdle right now? should I be in stocks or T-bills?`

**Pass:** 5-tier verdict (STRONG EQUITY / LEAN EQUITY / NEUTRAL / LEAN T-BILLS / MAXIMUM T-BILLS) with the recommended Value-bucket equity/T-bill split.

### T2.4 — Value screener

**Prompt:** `run a value screen on AAPL, KO, JNJ, PG, MSFT, NVDA, GOOG, META, INTC, AMD`

**Pass:** 8-factor composite scores (P/E, P/FCF, ROE, ROIC, Operating Margin, D/E, Profit Margin, Insider) computed, regime-tightened thresholds applied, sector-capped Top-10 written to `~/clarion/watchlists/sp500-screen-YYYY-MM-DD.md`.

### T2.5 — Watchlist update

**Prompt:** `what's hit my watchlist?`

**Pass:** Reads the latest watchlist, fetches current prices, computes % move since the screen, flags >10% moves and trigger hits.

### T2.6 — Thesis write

**Prompts:**

1. `index KO's latest 10-K`
2. *(wait for completion)* `write a thesis on KO`

**Pass:** `~/clarion/theses/KO.md` exists with YAML metadata block, an OPENED history entry, and the "Why I Believe It" section seeded with draft citations from the Buffett-lens search.

### T2.7 — Thesis monitor

**Prompt:** `monitor my theses`

**Pass:** Per-thesis dashboard with refreshed price, recomputed Risk Environment, kill-condition check, and an EXIT/REDUCE/HOLD/ADD recommendation. Updated scores written back to each thesis file.

### T2.8 — Living letter

**Prompt:** `write the Q2 letter entry` *(adjust quarter to current date)*

**Pass:** `~/clarion/letters/{YEAR}-letter.md` updated with auto-filled regime snapshot + thesis-health table; narrative sections (What We Did, What We Learned, etc.) marked `[TODO]` for the user to fill in.

### T2.9 — Cross-skill composition (the magic test)

**Prompt:** `evaluate AAPL and if it's a buy, write a thesis on it`

**Pass:** Zo's router chains the workflow: index AAPL → wait → eval AAPL → if Add verdict, scaffold thesis.

**This is the test that proves the skill descriptions correctly express their dependencies and the router can string them together autonomously.**

## Tier 3 — Stress and regression

**Goal:** prove robustness against edge cases, error paths, and previously-fixed bugs.

### T3.1 — Bad ticker

**Prompt:** `index ZZZNOTREAL`

**Pass:** Surfaces a "ticker not in EDGAR" error. Does NOT silently succeed or fabricate.

### T3.2 — Search before index

**Prompt:** `what does FOOBAR say about supply chain?`

**Pass:** Returns no hits and suggests indexing first. Does NOT fabricate from training data.

### T3.3 — Re-run setup (idempotency + service-restart reminder)

**Prompt:** `set up Clarion again`

**Pass:** All steps idempotent. Setup output explicitly tells Zo to restart `sec-indexer`. **This is the verification for the operator-doc patch:** editable `uv pip install -e` does NOT reload an already-running service, so the reminder must fire.

### T3.4 — Service restart

**Prompt:** `restart the sec-indexer service`

**Pass:** Zo invokes `update_user_service`. Service confirms restart. Re-running any T2.1 query picks up the freshly-installed source code.

### T3.5 — Citation discipline audit

After any T2.2, T2.6, or T2.9 output, manually verify:

- Every filing-derived claim has a canonical citation in the form `TICKER FORM filed YYYY-MM-DD → section`.
- No fabricated numbers — if the skill couldn't find a value, it says "the indexed sections don't address X" rather than inventing.
- yfinance numbers are flagged as point-in-time when they matter for high-conviction calls.

### T3.6 — Concurrent indexing

**Prompt:** `index latest 10-Ks for AAPL, GOOG, META, AMD, INTC, NFLX, TSLA, MSFT`

**Pass:** Queue accepts all 8. The `sec-indexer` service drains the queue serially. `status <ticker>` shows progress per ticker. None silently fail.

(Note: this is the indexer-bottleneck zone. For Stage 2 deep-dive workflows, prefer indexing one ticker at a time.)

### T3.7 — Skill-router routing for valuation question

**Prompt:** `is the market overvalued?`

**Pass:** Routes to `clarion-expected-return-calc` (not `regime-check`). Tests whether the question shapes in skill descriptions correctly disambiguate between the two.

### T3.8 — Skill-router routing for non-10-K SEC questions

**Prompt:** `show me META's executive compensation`

**Pass:** Routes to `clarion-sec-research` and indexes a DEF 14A (proxy statement). Tests the post-May-8 description expansion that advertises the full SEC form coverage.

### T3.9 — Recovery from missing data

Manually `rm -rf ~/clarion/sec/NVDA/`, then `search "Blackwell" --tickers NVDA`.

**Pass:** Reports zero hits, suggests re-indexing. Does NOT crash.

### T3.10 — Voice consistency

Place outputs from any two skills side-by-side. Verify:

- Both lead with results, not preamble.
- Both show the math (numbers from filings or market data).
- Both prefer Tier 1 sources (SEC filings, regime signals, market data) over Tier 3 (analyst estimates, sentiment).
- Section structure and tone are consistent.

## Reporting

For each executed test, record:

- Pass / Fail / Skipped
- One-line output excerpt or error message if Failed
- Time-to-completion (especially for indexing tests)

Bundle results into one chat message back to the maintainer.

## Maintenance

Update this test plan when:

- A new `clarion-*` skill ships → add a Tier 2 case for it
- A bug is found in production → add a Tier 3 regression case so it can't return silently
- A skill's description changes → update the routing tests in Tier 3

Source: `github.com/jingerzz/clarion-intelligence-system`. Last reviewed against commit `c817bb7` (2026-05-08).
