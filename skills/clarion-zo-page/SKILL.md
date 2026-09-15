---
name: clarion-zo-page
description: Canonical workflow for building, editing, refreshing, and verifying Clarion thesis pages on cis.zo.space. Use whenever creating a new /<ticker> page, editing an existing one, refreshing a page after earnings or a thesis review, syncing the homepage registry, or debugging a broken/stale/unreadable page. Covers template selection by verdict, safe edit_space_route practice, live-data rules, content readability standards, homepage registry sync, global mobile CSS, and the verification ladder. Companion to clarion-thesis-write (owns the templates and validate-page.py) and clarion/ZO-SPACE-VERIFY.md (owns the verification protocol).
compatibility: Created for Zo Computer
metadata:
  author: cis.zo.computer
  category: Clarion
  display-name: Clarion Zo Space Page Workflow
---

# Clarion Zo Space page workflow

One workflow for every touch of a thesis page. This skill exists because quality escapes
came from scattered process, not missing tools: `/rddt` served an error boundary to every
visitor for an unknown period, DECK shipped tabs that blanked on click, IREN's page sat
35 days stale while self-flagging it, and an `edit_space_route` merge dropped a closing
brace mid-refresh (2026-08-28). Each had a rule somewhere; nothing tied them together.

**Canonical companions — read, don't duplicate:**
- Verification protocol: `clarion/ZO-SPACE-VERIFY.md`
- Templates + validator: `Skills/clarion-thesis-write/assets/` and `scripts/validate-page.py`
- Thesis file (source of truth for content): `clarion/theses/{TICKER}.md`

## Ground rules (every flow)

1. **Live data first.** Fetch price/52w/mcap/P/E from yfinance *before* building or editing.
   Never pass a guessed or remembered price into page code. T-bill yield = `^IRX`.
2. **The thesis file is canonical.** Kill conditions, valuation scenarios, add/trim zones,
   and position plan on the page must mirror `clarion/theses/{TICKER}.md` — never edit the
   page's numbers without the file (drift between the two is a recurring, logged defect).
3. **One concern per `edit_space_route` call.** Get the current code with `get_space_route`
   first. If a `code_edit` is getting long, split it. Inspect every sync result — an LLM
   merge has dropped a component's final closing brace and shipped an error page.
4. **Tab bar edits change the ids and the `tab===` guards in the same edit.** This is the
   DECK blank-tab bug class. Then run Check 0 immediately.
5. **Never report done without the verification ladder** (bottom of this file).

## Flow 1 — New page

1. Verdict decides the template:
   - **Add / Hold / Watchlist** → `Skills/clarion-thesis-write/assets/zo-space-page-template.tsx`
     (5 tabs: Core Thesis w/ kill conditions, SEC Evidence w/ citations, Valuation
     bear/base/bull, Position Mgmt, Screener)
   - **Skip** → `Skills/clarion-thesis-write/assets/zo-space-page-template-skip.tsx`
     (4 sections: Why I'm Passing, SEC Evidence, Valuation w/ price-that-changes-mind,
     Revisit Triggers)
2. Fetch live data (Ground rule 1). Populate content from the thesis file (Ground rule 2).
3. Required chrome: nav brand `Clarion Intelligence Systems` wrapped in an anchor to
   `https://cis.zo.space` (validator enforces); root element carries class `thesis-root`
   (without it the page gets **no mobile CSS treatment**); footer attribution.
4. `write_space_route(path="/ticker", route_type="page", public="true")` — thesis pages
   are public.
5. Register on the homepage (see Registry section) — an unregistered page is reachable by
   URL but invisible on the homepage.
6. Run the verification ladder.

## Flow 2 — Edit existing page

1. `get_space_route(path)` — read what is actually there before planning edits.
2. Apply Ground rules 3 and 4. Prefer several small `edit_space_route` calls over one big one.
3. If a sync errors or the route starts serving the error boundary: `get_space_route` again,
   diff against intent, fix surgically. Check `get_space_errors` too.
4. Run the verification ladder.

## Flow 3 — Data refresh (earnings, thesis review, staleness)

1. Update (or confirm current) the thesis file **first**, then mirror to the page.
2. yfinance for every figure; update the `priceAsOf` date; clear or refresh any
   self-flagged "Stale" badge.
3. Sync valuation scenarios and kill conditions from the file verbatim — including
   status/monitor columns if the page shows them.
4. Update the homepage registry entry (price, score, blurb) in the same pass.
5. Run the verification ladder, plus `curl -s https://cis.zo.space/api/theses-list`
   and confirm the ticker's fields match.

## Content readability standards

The validator checks structure, not prose. Before delivery, hold the page to these:

- **Verdict first.** The hero states Add/Hold/Watchlist/Skip and the one-line why before
  anything else. A visitor should know the stance in 5 seconds.
- **Every number carries an as-of date.** Price, valuation, short interest, ARR — undated
  numbers are how pages rot invisibly.
- **Every filing claim carries a citation** (form + filing date, e.g. "10-K filed
  2026-08-27"). No orphan claims in SEC Evidence.
- **Steelman the other side.** Add/Hold pages carry the bear case; Skip pages carry what
  would change the verdict. One-sided pages read as marketing.
- **Plain language.** Define jargon inline or link the glossary. Public readers are not
  assumed to know ARR, prob-weighted fair value, or kill conditions.
- **Kill conditions are specific and current** — each with its monitor source and status,
  matching the thesis file.

## Homepage registry

- `clarion/homepage-theses.json` is the single source for homepage cards, served by
  `/api/theses-list`, rendered sorted by score desc.
- `register-thesis-on-homepage.py` is **missing** (recurring — a user rule still references
  it). Edit the JSON directly: upsert by ticker with `name`, `action`, `actionColor`,
  `price`, `score`, `description`, `tags`, `tagColor`. The API picks the file up live.
- Verify: `curl -s https://cis.zo.space/api/theses-list | python3 -c "import sys,json; ..."` or grep the ticker.

## Global styling and mobile

- Mobile is handled **globally**, not per page: `/assets/site.css` (source:
  `clarion/site-assets/site.css`, wired via space settings `custom_head_html`) collapses
  `repeat()` grids under 640px so stat tiles fit phones.
- Publish changes with `update_space_asset`, then **bump the `?v=` param in
  `custom_head_html`** — Cloudflare caches the asset 4h and visitors otherwise keep the
  old copy.
- The mobile rule only targets `repeat(` grids. An explicit track list like
  `"80px 110px 90px 1fr"` is a label/value row and gets scrambled by a blanket override —
  build multi-column tables as a flex column of rows instead.
- Rules are scoped to `.thesis-root`; a page without that class gets nothing.
- Mobile check (validator does NOT cover this):
  `agent-browser set viewport 390 844`, then per route eval
  `document.documentElement.scrollWidth - window.innerWidth` — ≤2 is clean.

## Verification ladder (before saying "done")

Full protocol with rationale: `clarion/ZO-SPACE-VERIFY.md`. The short form:

```bash
# Check 0 — static, run constantly (milliseconds)
python3 /home/workspace/Skills/clarion-thesis-write/scripts/validate-page.py --ticker TICKER

# Check 1 — render, before delivery and after any tab-bar edit
python3 /home/workspace/Skills/clarion-thesis-write/scripts/validate-page.py --ticker TICKER --render

# Check 2 — look at it (proves layout only, NOT the other tabs)
agent-browser open http://localhost:3099/TICKER && sleep 3
agent-browser screenshot /tmp/page.png --full     # flag is --full/-f, see traps below

# Check 3 — data is live, links resolve, registry updated
# price matches yfinance; /api/thesis/TICKER matches thesis YAML;
# get_space_errors clean; /api/theses-list shows the ticker
```

- `[FAIL]` = broken, fix before delivery. `[WARN]` = renders but sparse — does **not**
  affect exit code and must not be treated as breakage. That calibration is load-bearing.
- A screenshot only exercises the default tab. `--render` is the only check that catches
  a page that parses fine and is dead or blank at runtime.

## Tooling traps

- `agent-browser screenshot` full-page flag is `--full` / `-f`, **not** `--full-page`.
  Arguments are positional (`[selector] [path]`), so a wrong flag silently writes a PNG
  literally named `--full-page` and still prints "✓ Screenshot saved". `ls` the target
  path after every screenshot.
- Do not trust `agent-browser snapshot` for post-click state — it serves a cached tree.
  Use `agent-browser eval` to read the live DOM.
- `validate-page.py --all` covers **every** route, not just thesis pages. Never narrow it —
  excluded routes are how `/rddt` died unnoticed.
- After editing `validate-page.py`, run `Skills/clarion-thesis-write/tests/selftest.sh`
  (3 fixtures). A checker nobody tests silently rots.
- Daily automation **"Clarion Zo Space Page Health Sweep"** (7am ET) runs the full
  static + render sweep and SMSes only on failure. It is the backstop, not the substitute,
  for the ladder above.
