# Architecture

This doc captures the load-bearing decisions for Clarion Intelligence System (CIS). Read this before changing the LLM client, the skill manifests, or the SEC indexer.

## Audience

Zo Computer users. Free tier and subscriber tier both supported. Skills install from Zo chat via the public Zo Skills registry.

## Brand context

CIS is the **research/product layer** of the Clarion umbrella.

| Layer | Repo | Visibility | Purpose |
|---|---|---|---|
| Engine / data | [Clarion Trading Platform](https://github.com/jingerzz/Clarion-trading-platform) | Private (multi-collaborator) | Trading signals, market data, MCP servers, tastytrade integration |
| Research / product (this repo) | clarion-intelligence-system | Public, MIT | Buffett-style research skills for Zo users |

CIS is a **clean re-implementation**, not a fork. No code from Clarion Trading Platform ships in this repo — we re-derive the regime/signal logic from first principles in `lib/ai_buffett_zo/`.

## Distribution

Published via the **External path** of [`zocomputer/skills`](https://github.com/zocomputer/skills): one entry in their `external.yml` points at this repo, the registry pulls our skills under `External/clarion-*/`. Updates here flow to users on the registry's `bun sync` cycle. No per-skill PR friction.

Users install with chat commands like `install the clarion-setup skill`. Zo curls `manifest.json`, untars the slug folder into the user's `~/Skills/`. No `gh clone` required from the user side.

## The big architectural pivot: skills, not MCP servers

Clarion Trading Platform exposes MCP servers (`spy-tlt-strat`, `single-stock-strat`, `sec-rag`) over stdio. **That pattern does not work on Zo.** Zo is itself an MCP server (`https://api.zo.computer/mcp`) — it exposes its own tools to external MCP clients, but it does not host external MCP servers.

The Zo-native pattern is:

- **Skills** are the orchestration layer (folder packages with `SKILL.md` + frontmatter, indexed into Zo's chat by description match).
- **Bundled scripts** in each skill (`skills/*/scripts/*.py`) are the execution layer. SKILL.md instructs Zo to run them via the `Run command` tool; stdout/stderr come back into the chat turn.
- A **shared Python library** (`lib/ai_buffett_zo/`) gets `uv pip install -e`'d once during `clarion-setup`. Every skill's scripts import from it.
- **Zo Services** are reserved for genuinely long-running work — primarily the SEC indexer (process mode, no public port).

## LLM wiring

All Zo-hosted model calls go through `POST https://api.zo.computer/zo/ask`, **not** an OpenAI-compatible endpoint. Contract:

- `Authorization: Bearer ${ZO_API_KEY}` — token issued in Settings → Advanced
- `model_name` — selects the model (e.g. `zo:openai/gpt-5.4-mini`)
- `output_format` — JSON Schema for strict-shape output

### Schema constraints (verified against the live API)

- Scalar `type` must be `"string"` | `"number"` | `"boolean"`. **`"integer"` is rejected.** Use `"number"` and cast on read.
- Schema strictness varies by model. `zo:openai/gpt-5.4-mini` is strict. `zo:minimax/minimax-m2.7` is best-effort and may rename keys or drop fields.
- The LLM client (`lib/ai_buffett_zo/llm/zo_client.py`) implements a **repair pass**: maps common alias keys (e.g. `summary` → `one_sentence_summary`, `bullets` → `key_points`) and fills missing required fields with defaults. Downstream code never sees a malformed object.

### Default model selection

| Role | Default model | Rationale |
|---|---|---|
| Indexing (high volume) | `zo:openai/gpt-5.4-mini` | Free tier, strict schema, 400k ctx, ~13s/section |
| Indexing fallback | `zo:minimax/minimax-m2.5` | Free tier, ~7s/section, strict-with-repair |
| Reasoning / synthesis | `zo:anthropic/claude-opus-4-7` or `zo:openai/gpt-5.5` | Subscriber tier, used for thesis writing, screener rationale, letter prose |

User can override per-skill via `~/clarion/config.json`. No model strings hard-coded in skill scripts — all routed through `zo_client`.

### Auth model

The `ZO_API_KEY` is **not an external provider key**. It's a Zo-issued bearer that authenticates our service as the user, so calls are billed against their Zo monthly credits — same pool as their chat usage. Free-tier models cost less in credits.

`ZO_CLIENT_IDENTITY_TOKEN` is auto-injected during agent turns but **not** in long-running services. Hence the user-issued token is required for `sec-indexer`.

### Permissioning

Skills omit the `allowed-tools` frontmatter field. Permissions are governed by Zo persona scopes (`set_persona_scopes`). Verified against the live registry: only one Community skill uses `allowed-tools` and the validator doesn't enforce its vocabulary anyway.

## Data layer

- Market data: yfinance only. No tastytrade, no broker APIs.
- Cache: CSVs at `~/clarion/data/equities/{TICKER}-history.csv`. Lazy refresh — fetch when stale, append on append.
- SEC filings: pulled via SEC EDGAR (HTTP), gzipped on ingest.

## SEC RAG

- Vectorless mode (`semantic_search: false`). Keyword + tree + reasoning-pass retrieval. Mirrors the production setting in Clarion sec-rag, which scores 98.7% on FinanceBench without embeddings.
- Storage rules (100 GB practical workspace ceiling — no kernel quota, but Zo enforces upstream):
  - **Gzip** raw filings on ingest.
  - **Prune** exhibits we don't analyze (large XBRL blobs, Ex-99 attachments) after extracting numeric data.
  - Indexed JSON trees stay small and rebuildable from raw.
  - **DuckDB / Parquet** for dense numeric tables (income statement, balance sheet, ratios) — ~10× smaller than JSON.
- Workspace layout:
  ```
  ~/clarion/
    config.json
    data/equities/        yfinance CSVs
    sec/<TICKER>/         per-ticker indexed trees + raw.gz
    queue/                pending indexing jobs (sec-indexer service watches)
    theses/               markdown thesis files
    watchlists/           dated screen outputs
    letters/              annual living investor letter
  ```

## Voice & style

Skill output prose follows the Design-Language doc (ported into `docs/DESIGN-LANGUAGE.md` in Phase B):

- Buffett clarity, Munger bluntness, Druckenmiller tactical awareness.
- Show the math. Always.
- **Never fabricate financial data.** Cite the filing or the data source.
- Tier 1 (SEC filings, regime signals, market data) > Tier 2 (verified external) > Tier 3 (analyst estimates, sentiment).

Output formatting helpers live in `lib/ai_buffett_zo/voice/templates.py`.

## Phasing

| Phase | Status | Deliverables |
|---|---|---|
| A | In flight | lib v0.1, sec-indexer service, three skills (setup / regime-check / sec-research), end-to-end Zo test |
| B | Planned | Six remaining skills for full feature parity (single-stock-eval, value-screener, thesis-write, thesis-monitor, expected-return-calc, watchlist-update, living-letter-update) |
| C | Planned | Standalone course repo for Zo users learning the system |

## Repo layout

```
clarion-intelligence-system/
├── README.md             For Zo users
├── ARCHITECTURE.md       This file (for developers)
├── LICENSE               MIT
├── lib/ai_buffett_zo/    Shared Python library — uv pip install -e during setup
│   ├── llm/              zo_client.py — /zo/ask wrapper with repair pass
│   ├── data/             yfinance + CSV cache
│   ├── regime/           SPY/TLT/RSP color logic
│   ├── secrag/           pageindex fork, vectorless, Zo-LLM backend
│   ├── voice/            Output formatting, Design-Language helpers
│   └── theses/           Thesis read/write/health-score
├── skills/               One subdir per skill, registered via External path
│   └── <skill-slug>/
│       ├── SKILL.md
│       ├── scripts/
│       └── references/
├── services/
│   └── sec-indexer/      Process-mode Zo Service
├── docs/                 Adapted public-safe versions of MISSION/DESIGN-LANGUAGE/etc.
├── templates/            Thesis, watchlist, letter templates
├── data/                 .gitignore'd except sample/ for tests
└── scripts/
    └── zo_ask_prototype.py   Validated /zo/ask client — seed for zo_client.py
```
