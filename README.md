# Clarion Intelligence System

Buffett-style investment research, packaged as installable skills for [Zo Computer](https://docs.zocomputer.com/).

Three things you can do from Zo chat:

1. **Read market regime** — SPY / TLT / RSP color, hurdle rate, what to do about it.
2. **Pull and analyze SEC filings** — single ticker or a watchlist, indexed and queryable in plain English.
3. **Evaluate a single stock** — moat, management, financial trends, kill conditions, position-sizing context.

Built around principles from Berkshire Hathaway and Buffett's annual letters, adapted to a system you can run yourself. Conservative, show-the-math, never fabricates data — and **tells you to do nothing when nothing is the right answer**. When the regime is elevated and valuations are stretched, the screener returns an empty top list, the expected-return calc lands at MAXIMUM T-BILLS, and the watchlist surfaces no triggers. That's a feature, not a gap.

## Install

The autonomous portion of the install runs in ~30 seconds; you spend ~2 minutes creating one Zo secret. Total ~3 minutes start-to-finish.

### Quick start

Paste this into Zo chat:

> Install the clarion-setup skill and set up Clarion.

Zo installs the bootstrap skill, clones the repo, installs the library, creates the workspace, installs all sibling skills, and registers the background service — autonomously, ~30 seconds. It pauses **once** for two inputs from you (your SEC EDGAR name+email AND creating the `ZO_API_KEY` Zo secret), then verifies the service is running and reports.

Persona routing (the 7 Clarion personas + 8 chat rules that enforce regime-first framing and persona handoff) is **opt-in via a separate prompt** after the install completes — see [Add persona routing (optional)](#add-persona-routing-optional) below. The bare install gives you everything to evaluate stocks and pull SEC filings; persona routing is a chat-UX layer on top.

### What you'll be asked at the human checkpoint

When the skill pauses near the end, it surfaces **two things at once** — surface both together so you can multitask:

**(a) SEC EDGAR identification.** SEC requires every API consumer to identify itself in the User-Agent header. Type one line in chat when asked:

```
Jane Doe jane@example.com
```

Your real name and email — sent in every SEC request from your machine. Only you and SEC see it. Required by [SEC's fair-access policy](https://www.sec.gov/os/accessing-edgar-data).

**(b) Create the `ZO_API_KEY` secret in Zo Settings.** The `sec-indexer` background service needs a Zo-issued token to call Zo models on your behalf. Chat skills get a token auto-injected; background services don't, so you create one explicitly. **No external API keys** — the token is Zo-issued and bills against your Zo monthly credits.

In a separate browser tab while you reply to (a):

1. Open Zo Settings (top-right menu icon → **Settings**).
2. Go to **Advanced → Access Tokens**. Click **Create token**. Name it anything (`clarion-sec-indexer` is a good default). **Copy the token value** — it starts with `zo_sk_`.
3. Go to **Advanced → Secrets**. Click **Create secret**.
4. **Name:** type **exactly** `ZO_API_KEY` (uppercase, with the underscore — the indexer looks up this exact name; lowercase or hyphens won't work).
5. **Value:** paste the token from step 2.
6. Save.

Once both are done — SEC identification typed in chat AND `ZO_API_KEY` secret created — reply `done`. The skill writes your SEC identification to `~/clarion/config.json`, restarts the service, verifies it's running, and reports.

That's the only manual config in the whole install.

> **If Zo's chat agent didn't pause and ask you,** prompt it explicitly: *"walk me through the human checkpoint for Clarion setup — I need to provide my SEC EDGAR identification and create the ZO_API_KEY secret."* The full instructions live in the `clarion-setup` skill's SKILL.md.

### What the install does behind the scenes

For reference — the Quick-start prompt above triggers all of this autonomously:

1. Installs the `clarion-setup` bootstrap skill from the Zo registry
2. Clones this repo into `/home/workspace/clarion-intelligence-system`
3. Installs the `ai_buffett_zo` Python library (`uv pip install -e lib/`)
4. Creates the `~/clarion/` workspace tree (`data/`, `sec/`, `queue/`, `theses/`, `watchlists/`, `letters/`) plus default `config.json`
5. Auto-installs all nine sibling `clarion-*` skills under `/home/workspace/Skills/`
6. Registers the `sec-indexer` background service (in FATAL state until the human checkpoint finishes — that's expected)
7. **Pauses for the human checkpoint** (see above)
8. After your input: writes SEC identification to `config.json`, restarts `sec-indexer`, verifies via `service_doctor`, reports completion

Setup is idempotent — safe to re-run. On a clean re-run (nothing customized, secret already exists, SEC identification already set), the human checkpoint is skipped entirely.

The autonomous SEC indexer service is **queue-driven** — it idles after install with zero API calls until you (or a Clarion skill) explicitly enqueues a filing via `clarion-sec-research index TICKER`. Nothing is pre-indexed.

### Use it conversationally

That's it. Now ask Zo things like:

- "What's the market regime right now?"
- "Evaluate AAPL." *(indexes the latest 10-K + runs the Buffett-lens eval — ~2 minutes on first invocation)*
- "Has there been any insider activity at NVDA?" *(Form 4)*
- "Run a value screen at my hurdle rate."
- "Write a thesis on TTD."
- "What's hit my watchlist this week?"

### Add persona routing (optional)

The skills above are functional standalone. Personas + routing rules add the **chat-layer discipline** — regime-first framing, automatic persona handoff (Macro Sentinel → Analyst → Thesis Architect → Portfolio Manager), kill-condition enforcement, and the return-to-default rule for non-investment queries.

To add persona routing, paste this prompt into Zo chat:

> Install Clarion personas and routing rules.

This takes ~3 minutes (it parses `docs/PERSONAS-AND-RULES.md` and creates 7 personas + 8 rules via `create_persona` / `create_rule`). After it's done, Clarion responses route through specialist personas automatically based on what you ask. See [`docs/PERSONAS-AND-RULES.md`](./docs/PERSONAS-AND-RULES.md) for the full persona/rule definitions.

To skip entirely: do nothing. The Buffett-style evaluation skills, regime check, value screener, thesis tools, and SEC indexing all work without personas — they just answer in Zo's default tone instead of routing through specialist voices.

## Updating

When upstream ships fixes, re-run `clarion-setup` to pull them down:

> set up Clarion

This `git pull`s the source, re-installs the library, and refreshes the sibling skills under `/home/workspace/Skills/`. On a clean re-run (secret already exists, sec_user_agent already set), the human checkpoint is skipped automatically and the whole flow is autonomous.

The skill restarts `sec-indexer` automatically as part of the re-run, so updated library code is loaded into the running process. No separate "restart the service" command needed.

Personas and routing rules are **not** modified by `clarion-setup` re-runs — they're owned by the user (set via the optional persona install prompt). If you want updated persona/rule text after pulling new upstream docs, run *"install Clarion personas and routing rules"* again; it'll ask before replacing any existing entries.

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
- A Zo access token, created **during install** at the human checkpoint described above — used by the SEC indexer to call models on your behalf, billed against your Zo credits
- A name and email for SEC EDGAR identification (provided during install) — public to SEC only
- ~100 GB workspace headroom is plenty even for a 50-ticker watchlist

No external API keys. No broker accounts. No real-time data feeds.

## Data sources

- Market data: [yfinance](https://github.com/ranaroussi/yfinance) (delayed, free)
- SEC filings: [SEC EDGAR](https://www.sec.gov/edgar) (free, official)
- LLM inference: Zo-hosted models (defaults to free-tier `zo:openai/gpt-5.4-mini` for indexing). Configurable: edit `indexing_model`, `indexing_fallback_model`, or `reasoning_model` in `~/clarion/config.json`, then restart the `sec-indexer` service for the new values to take effect. Free-tier users hitting subscriber-tier reasoning prompts can swap `reasoning_model` to a free-tier model here.

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
