# Clarion Intelligence System

Buffett-style investment research, packaged as installable skills for [Zo Computer](https://docs.zocomputer.com/).

Three things you can do from Zo chat:

1. **Read market regime** — SPY / TLT / RSP color, hurdle rate, what to do about it.
2. **Pull and analyze SEC filings** — single ticker or a watchlist, indexed and queryable in plain English.
3. **Evaluate a single stock** — moat, management, financial trends, kill conditions, position-sizing context.

Built around principles from Berkshire Hathaway and Buffett's annual letters, adapted to a system you can run yourself. Conservative, show-the-math, never fabricates data — and **tells you to do nothing when nothing is the right answer**. When the regime is elevated and valuations are stretched, the screener returns an empty top list, the expected-return calc lands at MAXIMUM T-BILLS, and the watchlist surfaces no triggers. That's a feature, not a gap.

## Install

A brand-new Zo user gets fully set up in ~3-5 minutes. The entire install is two chat prompts and one batched human checkpoint near the end (your SEC EDGAR name+email and creating one Zo secret). Everything else — code, library, data tree, sibling skills, background service, personas, routing rules — is autonomous.

### 1. Install the bootstrap skill

In Zo chat:

> install the clarion-setup skill

`clarion-setup` is the bootstrap — install this one **first** before any other `clarion-*` skill.

### 2. Run the setup skill

In Zo chat:

> set up Clarion

The skill runs autonomously through these steps:

1. Clone this repo into `/home/workspace/clarion-intelligence-system`
2. Install the `ai_buffett_zo` Python library (`uv pip install -e lib/`)
3. Create the `~/clarion/` workspace tree (`data/`, `sec/`, `queue/`, `theses/`, `watchlists/`, `letters/`)
4. Write `~/clarion/config.json` with sane model defaults (all Zo-hosted)
5. Auto-install all nine sibling `clarion-*` skills under `/home/workspace/Skills/`
6. Register the `sec-indexer` background service (will be in FATAL state until step 3 below — that's expected)
7. Install all 7 Clarion personas in Zo Settings → AI → Personas
8. Install the 8 Clarion routing rules (Rule 3 + Rules 5–11) in Zo Settings → AI → Rules

Then it pauses for **one batched human checkpoint** — described in Step 3 below. After your input, the skill resumes autonomously: writes your SEC EDGAR identification to `~/clarion/config.json`, restarts the `sec-indexer` service, verifies it's running, and reports completion.

Setup is idempotent — safe to re-run any time to pull source updates. It will ask before replacing any personas or rules you've customized.

### 3. The one batched human checkpoint

When the skill pauses, it asks for **two things at once** — surface them together so you can multitask:

**(a) SEC EDGAR identification.** SEC requires every API consumer to identify itself in the User-Agent header. Type one line in chat:

```
Jane Doe jane@example.com
```

(Your real name and email — sent in every SEC request from your machine. Only you and SEC see it. Required by SEC's [fair-access policy](https://www.sec.gov/os/accessing-edgar-data).)

**(b) Create the `ZO_API_KEY` secret in Zo Settings.** The `sec-indexer` background service needs a Zo-issued token to call Zo models on your behalf. Chat skills get a token auto-injected; background services don't, so you have to create one explicitly. The token is **Zo-issued** and bills against your Zo monthly credits — same pool as chat usage. **No external API keys involved.**

In a separate browser tab while you reply to (a):

1. Open Zo Settings (top-right menu icon → **Settings**).
2. Go to **Advanced → Access Tokens**. Click **Create token**. Name it anything (`clarion-sec-indexer` is a good default). **Copy the token value** — it starts with `zo_sk_`.
3. Go to **Advanced → Secrets**. Click **Create secret**.
4. **Name:** type **exactly** `ZO_API_KEY` (uppercase, with the underscore — the indexer looks up this exact name; lowercase or hyphens won't work).
5. **Value:** paste the token from step 2.
6. Save.

Once both are done — your SEC identification typed in chat AND the `ZO_API_KEY` secret created — reply `done`. The skill will write your SEC identification to config.json, restart `sec-indexer`, verify it's running, and report.

That's the only manual config in the whole install.

> **If Zo's chat agent didn't pause and ask you,** prompt it explicitly: *"walk me through the human checkpoint for Clarion setup — I need to provide my SEC EDGAR identification and create the ZO_API_KEY secret."* The full instructions live in the `clarion-setup` skill's SKILL.md — the agent should walk you through them.

### 4. Use it conversationally

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

This `git pull`s the source, re-installs the library, refreshes the sibling skills under `/home/workspace/Skills/`, and — if there are doc updates — asks you before replacing any customized personas or rules. On a clean re-run (you didn't customize anything, secret already exists, sec_user_agent already set), the human checkpoint in step 3 is skipped automatically and the whole flow is autonomous.

The skill restarts `sec-indexer` automatically as part of the re-run, so updated library code is loaded into the running process. No separate "restart the service" command needed.

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
- [`docs/TEST-PLAN.md`](./docs/TEST-PLAN.md) — three-tier test plan you can run from Zo chat to validate your install (smoke / functional / stress)
- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — design decisions, library layout, and the `/zo/ask` LLM wiring contract
