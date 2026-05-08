---
name: clarion-setup
description: Bootstraps the Clarion Intelligence System on Zo Computer. Run this once after installing the skill — clones the source repo, installs the ai_buffett_zo Python library, creates the ~/clarion/ workspace, writes default config, and registers the sec-indexer background service. Idempotent (safe to re-run). Use when the user asks to "set up Clarion", "install Clarion", or after they install any other clarion-* skill before it has been bootstrapped.
metadata:
  author: cis.zo.computer
  category: External
  display-name: Clarion Setup
  homepage: https://github.com/jingerzz/clarion-intelligence-system
---

# Clarion Setup

Bootstraps Clarion Intelligence System on a Zo workspace. Run this once before any other `clarion-*` skill.

## What you do

Run the steps below in order. Stop and surface any failure to the user immediately — do not proceed past a failure.

### Step 1 — Clone or update the source repo

The repo holds the Python library, the `sec-indexer` service code, and templates.

If `/home/workspace/clarion-intelligence-system` does NOT exist:

```bash
gh repo clone jingerzz/clarion-intelligence-system /home/workspace/clarion-intelligence-system
```

If it exists, update it:

```bash
git -C /home/workspace/clarion-intelligence-system pull --ff-only
```

### Step 2 — Run the setup script

```bash
python /home/workspace/clarion-intelligence-system/skills/clarion-setup/scripts/setup.py
```

The script is idempotent. It will:

- Install the `ai_buffett_zo` library editable (auto-detects whether to use `--system`)
- Create the `~/clarion/{data/equities,sec,queue,theses,watchlists,letters}/` data tree
- Write a default `~/clarion/config.json` (preserves any existing config)
- Verify the `sec-indexer` console script is on PATH
- Print service registration parameters between `--- BEGIN SERVICE_REGISTRATION ---` and `--- END SERVICE_REGISTRATION ---`
- Print a final `SETUP_RESULT: ok` line on success, or `SETUP_RESULT: error: <reason>` on failure

If you do NOT see `SETUP_RESULT: ok`, surface the error to the user verbatim and stop.

### Step 3 — Confirm or create the ZO_API_KEY secret

**Scope:** This step is only needed because of the `sec-indexer` **background service**. The other Clarion skills (`clarion-regime-check`, `clarion-sec-research`, etc.) run inside chat agent turns, which auto-inject `ZO_CLIENT_IDENTITY_TOKEN`, so they need no token setup. The indexer runs as a persistent process outside agent turns, has no auto-injected identity, and so needs a long-lived bearer.

The token is **not** an external provider key (no OpenAI / Anthropic / Minimax keys involved). It's Zo-issued and calls made with it are billed against the user's Zo monthly credit pool, same as their chat usage.

**Decision — fresh install vs. re-run:**

- If the user already has a Zo secret named exactly `ZO_API_KEY` (most likely on a re-run), skip to Step 4.
- Otherwise (most likely on a first install), do the verbatim-paste step below.

**CRITICAL — paste the user-action block verbatim.** The setup script's stdout includes a block bounded by `--- BEGIN USER_ACTION_REQUIRED ---` and `--- END USER_ACTION_REQUIRED ---`. **Copy the contents of that block (everything between the two sentinels) into the chat exactly as written. Do not summarize, paraphrase, or condense.**

The block is dummy-proofed for a non-technical user: it has the exact menu paths, the exact secret name (`ZO_API_KEY`, uppercase, with underscore — the most error-prone part), the numbered sequence, and a note about UI variations. Compressing it removes the dummy-proofing.

After pasting the block:

1. Wait for the user to reply with `done` (or any clear confirmation).
2. If they reply with a question instead of confirmation (e.g. "I can't find Settings"), help them — but lead with the same explicit substeps from the user-action block, not your own paraphrase.
3. Once confirmed, proceed to Step 4.

### Step 4 — Register the sec-indexer service

Use the `register_user_service` agent tool with these exact parameters (also printed by setup.py in the SERVICE_REGISTRATION envelope):

- **label**: `sec-indexer`
- **mode**: `process`
- **entrypoint**: `sec-indexer`
- **workdir**: `/home/workspace`
- **env_vars**: `{"ZO_API_KEY": "$ZO_API_KEY"}`
- **description**: `Clarion sec-indexer — background SEC EDGAR filing indexer`

The `$ZO_API_KEY` value is shell-style syntax telling Zo to resolve from the user's secret of the same name (created in Step 3) at service start. Use the snake_case parameter names exactly — `workdir` and `env_vars` — these are the canonical keys Zo's tool accepts.

Confirm registration succeeded (the tool should return a service ID like `svc_…`).

### Step 5 — Verify and report

Run a final check:

```bash
sec-indexer --help
```

If it prints help text, all components are in place.

Tell the user:

> Clarion is set up.
>
> - Source: `/home/workspace/clarion-intelligence-system/`
> - Workspace data: `~/clarion/`
> - Background service: `sec-indexer` (running)
>
> Next, install the skills you want to use. Recommended starter set:
> - **clarion-regime-check** — SPY/TLT/RSP regime + hurdle rate
> - **clarion-sec-research** — pull, index, search SEC filings (10-K, 10-Q, Form 3/4/5, 8-K, DEF 14A, etc.)
>
> Or the full set: `clarion-single-stock-eval`, `clarion-expected-return-calc`, `clarion-value-screener`, `clarion-thesis-write`, `clarion-thesis-monitor`, `clarion-watchlist-update`, `clarion-living-letter-update`.
>
> Once any of those are installed, just ask me things like *"what's the market regime?"*, *"analyze NVDA's latest 10-K"*, or *"is the market overvalued?"*.

## Idempotency

Re-running this skill is safe. Each step:

- Repo clone: skipped if already cloned (just `git pull`)
- Library install: re-runs `uv pip install -e` (no harm)
- Data tree: `mkdir -p` (no harm)
- Config: preserved if present
- Service registration: if the user already has a `sec-indexer` service, `register_user_service` should report it exists; treat that as success.

### Re-running to pick up source updates

Editable installs (`uv pip install -e`) do NOT reload an already-running service — the `sec-indexer` process keeps the Python modules it imported at startup in memory. After a `git pull` brings in new code, you MUST restart the service for the changes to take effect.

If the user is re-running setup specifically to pull in upstream fixes (or you see behavior matching code that no longer exists in the repo), restart the service after Step 4:

- Use the `update_user_service` agent tool with the existing `sec-indexer` service ID and `action: restart` (or whatever the equivalent restart action is in the user's Zo environment).
- Confirm the service comes back up before re-running any failed `clarion-sec-research` query.

## On error

If any step fails, do not silently proceed. Read the error, summarize the cause, and offer the user the next step to take. Common cases:

- **`gh: command not found`** — Zo should ship `gh`. If missing, the user's workspace is in a non-standard state; ask them to contact Zo support.
- **`uv: command not found`** — same.
- **`uv pip install` fails with venv error** — the script tries `--system` automatically; if it still fails, ask the user to share the full error.
- **`register_user_service` fails** — surface the tool's error message; check whether `ZO_API_KEY` secret exists.
