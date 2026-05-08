# Clarion Intelligence System

Buffett-style investment research, packaged as installable skills for [Zo Computer](https://docs.zocomputer.com/).

Three things you can do from Zo chat:

1. **Read market regime** — SPY / TLT / RSP color, hurdle rate, what to do about it.
2. **Pull and analyze SEC filings** — single ticker or a watchlist, indexed and queryable in plain English.
3. **Evaluate a single stock** — moat, management, financial trends, kill conditions, position-sizing context.

Built around principles from Berkshire Hathaway and Buffett's annual letters, adapted to a system you can run yourself. Conservative, show-the-math, never fabricates data.

## Install

A brand-new Zo user gets fully set up in ~3-5 minutes. Most of that is the one-time access-token step.

### 1. Install the bootstrap skill

In Zo chat:

> install the clarion-setup skill

`clarion-setup` is the bootstrap — install this one **first** before any other `clarion-*` skill.

### 2. Run the setup skill

In Zo chat:

> set up Clarion

The skill will:

1. Clone this repo into `/home/workspace/clarion-intelligence-system`
2. Install the `ai_buffett_zo` Python library (`uv pip install -e lib/`)
3. Create the `~/clarion/` workspace tree (`data/`, `sec/`, `queue/`, `theses/`, `watchlists/`, `letters/`)
4. Write `~/clarion/config.json` with sane model defaults (all Zo-hosted, routed through `/zo/ask`)
5. Pause and ask you to create the `ZO_API_KEY` secret (next step)
6. Register the `sec-indexer` background service for you

Setup is idempotent — safe to re-run any time to pull source updates (see [Updating](#updating) below).

### 3. Create the `ZO_API_KEY` secret (one-time)

The `sec-indexer` runs as a persistent background service that needs to call Zo models on your behalf. It needs a long-lived bearer token (chat skills get one auto-injected, but background services don't). The token is **Zo-issued** and bills against your Zo monthly credits — same pool as chat usage. **No external API keys.**

When `clarion-setup` prompts you:

1. Open **Settings → Advanced → Access Tokens** in Zo. Create a new token (any name, e.g. `clarion-sec-indexer`). Copy the value (it starts with `zo_sk_`).
2. Open **Settings → Advanced → Secrets**. Create a secret named **exactly** `ZO_API_KEY` with the token as the value.
3. Tell Zo "done" and it will register the `sec-indexer` service for you.

That's the only manual config in the whole install.

### 4. Install the rest of the skills

Once setup is done, install whichever skills you want from the catalog. Recommended starter set:

> install the clarion-regime-check skill
> install the clarion-sec-research skill

Add the others as you reach for them — see the [Skills](#skills) section below.

### 5. Use it conversationally

That's it. Now ask Zo things like:

- "What's the market regime right now?"
- "Analyze NVDA's most recent 10-K risk factors."
- "Has there been any insider activity at NVDA?" *(Form 4)*
- "Evaluate KO as a long-term holding."
- "Run a value screen at my hurdle rate."
- "Write a thesis on TTD."
- "What's hit my watchlist this week?"

## Updating

When upstream ships fixes, re-run `clarion-setup` to pull them down:

> set up Clarion

This `git pull`s the source, re-installs the library, and re-runs the data-tree / config steps (all idempotent).

**Important:** an editable install (`uv pip install -e`) does NOT reload an already-running service. The `sec-indexer` keeps the modules it imported at startup in memory. After re-running setup, ask Zo to restart the service:

> restart the sec-indexer service

(Zo uses its `update_user_service` tool to do this.) Then any updated source code is loaded into the running process.

## Skills

All 10 skills ship together. Install whichever you need:

| Skill | What it does |
|---|---|
| `clarion-setup` | One-time bootstrap. Installs the library, creates the workspace, registers the `sec-indexer` service. **Install this first.** |
| `clarion-regime-check` | Reads SPY/TLT/RSP regime color and computes the equity hurdle rate. |
| `clarion-sec-research` | Pulls, indexes, and searches SEC filings — 10-K, 10-Q, Form 3/4/5 (insider transactions), 8-K, DEF 14A, S-1, 20-F, and more. |
| `clarion-single-stock-eval` | Buffett-lens evaluation of one ticker (moat, management, financial trends, risks). Requires `clarion-sec-research` to have indexed the ticker first. |
| `clarion-expected-return-calc` | Computes the equity-vs-T-bill split for the Value bucket from the Shiller CAPE + regime hurdle. 5-tier verdict. |
| `clarion-value-screener` | Runs an 8-factor value-quality screen and writes a sector-capped Top-10 watchlist. |
| `clarion-thesis-write` | Scaffolds a new thesis document in the canonical Clarion format. |
| `clarion-thesis-monitor` | Health-checks every active thesis: refresh prices, check kill conditions, recommend EXIT / REDUCE / HOLD / ADD. |
| `clarion-watchlist-update` | Refreshes the latest watchlist with current prices and flags what's moved or hit triggers. |
| `clarion-living-letter-update` | Updates the annual investor letter with a new quarterly entry. |

## Requirements

- A Zo Computer account (free tier works; subscriber tier unlocks higher-quality reasoning models)
- `clarion-setup` run **once** before any other `clarion-*` skill (it registers the `sec-indexer` background service every other skill depends on)
- A Zo access token (Settings → Advanced → Access Tokens), saved as a secret named `ZO_API_KEY` (Settings → Advanced → Secrets) — used by the SEC indexer to call models on your behalf, billed against your Zo credits
- ~100 GB workspace headroom is plenty even for a 50-ticker watchlist

No external API keys. No broker accounts. No real-time data feeds.

## Data sources

- Market data: [yfinance](https://github.com/ranaroussi/yfinance) (delayed, free)
- SEC filings: [SEC EDGAR](https://www.sec.gov/edgar) (free, official)
- LLM inference: Zo-hosted models (defaults to free-tier `zo:openai/gpt-5.4-mini` for indexing, configurable)

## License

MIT. See [LICENSE](./LICENSE).

## Reading order

For developers and curious users. Skim in order — MISSION and PRINCIPLES are conceptual context (read once), DESIGN-LANGUAGE and ALLOCATION-POLICY are operational references (consult during use).

- [`docs/MISSION.md`](./docs/MISSION.md) — what CIS is, who it's for, what you get from this repo and what you don't
- [`docs/PRINCIPLES.md`](./docs/PRINCIPLES.md) — the ten operational principles, anti-principles, and sanity test
- [`docs/DESIGN-LANGUAGE.md`](./docs/DESIGN-LANGUAGE.md) — voice, decision cascade, information hierarchy, anti-patterns, the Buffett Question Bank
- [`docs/ALLOCATION-POLICY.md`](./docs/ALLOCATION-POLICY.md) — four-bucket portfolio framework, regime-adaptive allocation, expected-return framework, drawdown rules
- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — design decisions, library layout, and the `/zo/ask` LLM wiring contract
