---
name: clarion-upside-vet
description: Vet an Upside Invest holdership-movers update (pasted from Slack) against Clarion investment standards. Parses the update, cross-references every ticker against active theses, live portfolio, and the latest watchlist, scores value-lane names on the 8-factor composite, routes speculative names to the YOLO checklist, auto-skips funds and unresolvable tickers with reasons, and maintains a signal track-record ledger with 30/90-day forward returns. Use whenever the user pastes an Upside Movers / holdership movers update, or asks "vet the Upside update", "what's the Upside track record?". Requires clarion-setup to have been run.
compatibility: Created for Zo Computer
metadata:
  author: cis.zo.computer
  category: Clarion
  display-name: Clarion Upside Vet
---

# Clarion Upside vet

Upside Invest (partner) sends holdership-movers digests to Jing's Slack — panel = linked
Upside portfolios, holder counts are net new/removed positions, not buy/sell volume. This
skill turns each pasted update into a triaged vet report plus a growing track-record ledger
that will eventually answer: **does this feed have alpha, or is it retail momentum chum?**

Decisions locked 2026-09-09: paste-triggered (Slack-only feed) · bucket-aware lenses
(value composite vs speculative YOLO checklist) · holdings signals surfaced in the report
only (no thesis-file writes) · weekly pass = composite depth, DEEP-DIVE handed to
`clarion-single-stock-eval` only on explicit go · file + chat summary output · ledger in v1.

## Workflow

1. **Parse the paste into JSON** — you (the chat agent) do this, no script. Write to
   `~/clarion/upside/inbox/{snapshot_date}.json`:

   ```json
   {
     "snapshot_date": "2026-09-07",
     "entries": [
       {"ticker": "AVGO", "company": "Broadcom Inc.", "section": "flagged",
        "signals": ["price -16.3% in 30d while panel bought: 83 buys vs 35 sells"],
        "note": "optional 'why now' text"}
     ]
   }
   ```

   `section` ∈ `flagged | new | piling_in | moving_out | fully_exited`. One entry per
   ticker per section — the script merges tickers appearing in multiple sections. Keep
   each signal as one plain-English string; keep panel stats (holders, pp change,
   buys/sells) inside the signal strings.

2. **Run the vet** (must be `/usr/local/bin/python` — ai_buffett_zo lives there):

   ```bash
   /usr/local/bin/python /home/workspace/Skills/clarion-upside-vet/scripts/vet.py \
       --input ~/clarion/upside/inbox/2026-09-07.json
   ```

   The script: cross-refs theses/portfolio/watchlist/ledger → fetches yfinance
   fundamentals → lanes each ticker → composites the value lane (regime-tightened
   thresholds) → appends ledger entries (idempotent) → backfills forward returns on
   prior entries → writes `~/clarion/upside/{date}-vet.md` with `[AGENT]` blanks.

3. **Finalize the report.** Fill every `[AGENT]` marker:
   - Holdings signals **Read** column — what the panel move means for our position, PM-voice.
   - Value lane **Final** verdicts — confirm or override the suggestion, one word from:
     `HOLDINGS-SIGNAL / DEEP-DIVE / QUALITY-WATCH / WATCHLIST / SPEC-REVIEW / SKIP`.
   - Speculative lane — score checklist items 1-5 (pass/fail each), then Final verdict.
     The script gives cash/debt/FCF/listing age; judge asymmetry and catalyst yourself
     from the update's "why now" notes plus what you know. No filings indexed = no
     position, full stop.
   - **Read-through for the book** — 3-6 sentences, the section Jing actually reads.

4. **Record final verdicts in the ledger** for any ticker where you overrode the
   suggestion (keeps the track record honest about what we decided vs what the rules said):

   ```bash
   /usr/local/bin/python .../vet.py set-verdict OKLO SKIP --date 2026-09-07
   ```

5. **Chat summary** — regime line, then holdings signals first, then anything that
   scored DEEP-DIVE, then one line on skips. Point at the report file. Do not
   re-render the tables in chat.

## Lanes and verdicts

| Lane | Who lands here | Standard applied |
|---|---|---|
| holdings | live position or thesis on file | surface signal; no auto-action; thesis file untouched |
| value | profitable, >$5B, listed >1yr | 8-factor composite, regime thresholds |
| spec | unprofitable, small, or fresh listing | YOLO checklist (in report); max 3% NLV, 10% bucket |
| auto_skip | funds/ETFs, unresolvable tickers | skipped with stated reason, never silently |

`DEEP-DIVE` means: worth running `clarion-single-stock-eval` — but only after Jing says go
(it needs indexed filings; offer `clarion-sec-research index TICKER` first). `WATCHLIST`
means composite ≥50 but below threshold — note it, no action. A "moving out" signal on a
holding is information, not an exit trigger — kill conditions live in the thesis, not the panel.

`QUALITY-WATCH` (added 2026-09-09): the name passes **every quality gate** (ROE, op margin,
D/E — data must be present; missing data disqualifies) and fails **only** the valuation gates
(P/E, P/FCF). "Wonderful business, wrong price" is not the same verdict as "bad business."
The script computes the **gate-clearing entry** — the price at which both valuation gates
clear at trailing fundamentals — and stores it in the report + ledger (`gate_entry`). Treat
it as a screen anchor, not a fair value: trailing FCF can be cyclically depressed (TXN's fab
capex is the canonical case), so the real add zone comes from a deep dive on normalized
earnings/FCF. When a QUALITY-WATCH price approaches its gate entry on a later run, that's
the cue to propose the deep dive.

## Track record

Every flagged ticker enters `~/clarion/upside/ledger.json` with price-at-flag. Later runs
(or `vet.py track-record`) backfill +30d/+90d returns and excess vs SPY. Once ~15 entries
mature, add a standing read on whether Upside flags carry alpha to the report's
track-record section. Until then: collecting, not concluding.

## Hard rules

1. Panel behavior is **sentiment evidence, never thesis evidence** — no thesis gets
   written or modified because holders piled in.
2. Never fabricate fundamentals; unresolved tickers stay unresolved with a reason.
3. Any resulting trade idea goes through `clarion/DEPLOYMENT-CHECKLIST.md` — this skill
   only triages.
4. Ledger is append-only via the script; never hand-edit entries, use `set-verdict`.
5. Fresh IPO in spec lane with no indexed filings → checklist item 5 fails → SKIP. No
   exceptions for a good story.

## On error

- **regime unavailable** — script continues without; run `clarion-regime-check`, then rerun
  if you want regime-tightened thresholds applied.
- **yfinance could not resolve ticker** — lands in Auto-skips; verify the symbol (Upside
  sometimes uses pre-listing or OTC symbols) and note it for Jing.
- **`VET_ERROR: no ledger entry`** — set-verdict before running the vet; run step 2 first.
- **"report exists, NOT overwritten"** — the script refuses to clobber a finalized report.
  Rerun with `--force-report` only if you intend to regenerate, then re-fill the `[AGENT]`
  markers (back the finalized file up first). Same-date reruns always refresh the ledger's
  `suggested_verdict`/`gate_entry` even when the report is left alone.
