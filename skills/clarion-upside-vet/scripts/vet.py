#!/usr/bin/env python
"""Clarion Upside vet — triage an Upside Invest holdership-movers update.

Takes a chat-agent-parsed JSON of the pasted Slack update, cross-references
every ticker against Clarion state (theses, live portfolio, latest watchlist,
prior vet ledger), fetches yfinance fundamentals, scores value-lane names on
the 8-factor composite, and writes a dated vet report skeleton plus a
signal-track-record ledger with 30/90-day forward-return backfill.

Run with /usr/local/bin/python (ai_buffett_zo is only importable there).

Usage:
    vet.py --input ~/clarion/upside/inbox/2026-09-07.json
    vet.py set-verdict AVGO HOLDINGS-SIGNAL --date 2026-09-07
    vet.py track-record
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path

CLARION_DATA_ROOT = Path(os.environ.get("CLARION_DATA_ROOT", "/home/workspace/clarion"))
UPSIDE_ROOT = CLARION_DATA_ROOT / "upside"
LEDGER_PATH = UPSIDE_ROOT / "ledger.json"
THESES_DIR = CLARION_DATA_ROOT / "theses"
PORTFOLIO_LATEST = CLARION_DATA_ROOT / "portfolio" / "latest.json"
WATCHLIST_DIR = CLARION_DATA_ROOT / "watchlists"

VERDICTS = ["HOLDINGS-SIGNAL", "DEEP-DIVE", "QUALITY-WATCH", "WATCHLIST", "SPEC-REVIEW", "SKIP"]
SECTION_LABELS = {
    "flagged": "Flagged",
    "new": "New to panel",
    "piling_in": "Piling in",
    "moving_out": "Moving out",
    "fully_exited": "Fully exited",
}
FUND_QUOTE_TYPES = {"ETF", "MUTUALFUND", "MONEYMARKET", "CEF", "FUND"}
FRESH_IPO_DAYS = 365


# ---- Cross-reference state ------------------------------------------------


def load_theses() -> dict[str, dict]:
    """Parse the yaml metadata block of every thesis file. Regex, not yaml lib —
    the blocks contain multi-line kill conditions we don't need."""
    out: dict[str, dict] = {}
    for f in sorted(THESES_DIR.glob("*.md")):
        try:
            text = f.read_text()
        except OSError:
            continue
        m = re.search(r"```yaml\n(.*?)```", text, re.DOTALL)
        if not m:
            continue
        block = m.group(1)
        meta: dict = {"file": f.name}
        for key in ("ticker", "status", "bucket", "add_zone", "base_case_fair_value", "trim_zone"):
            km = re.search(rf"^{key}:\s*(.+?)\s*$", block, re.MULTILINE)
            if km:
                meta[key] = km.group(1).strip()
        ticker = (meta.get("ticker") or f.stem.split("-")[0]).upper()
        # Prefer non-superseded file when duplicates exist (TTD vs TTD-V2)
        if ticker in out and "V2" not in f.stem:
            continue
        out[ticker] = meta
    return out


def load_positions() -> dict[str, dict]:
    try:
        data = json.loads(PORTFOLIO_LATEST.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, dict] = {}
    for acct in data.get("accounts", []):
        for p in acct.get("positions", []):
            sym = p.get("symbol", "").upper()
            if sym:
                out[sym] = p
    return out


def load_watchlist_tickers() -> tuple[str, set[str]]:
    files = sorted(WATCHLIST_DIR.glob("sp500-screen-*.md"))
    if not files:
        return "", set()
    latest = files[-1]
    tickers = set()
    for line in latest.read_text().splitlines():
        cell = re.match(r"\|\s*\**([A-Z]{1,5})\**\s*\|", line)
        if cell:
            tickers.add(cell.group(1))
    return latest.name, tickers


# ---- Ledger ---------------------------------------------------------------


def load_ledger() -> dict:
    if LEDGER_PATH.exists():
        return json.loads(LEDGER_PATH.read_text())
    return {"entries": []}


def save_ledger(ledger: dict) -> None:
    UPSIDE_ROOT.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(json.dumps(ledger, indent=1) + "\n")


def backfill_forward_returns(ledger: dict) -> list[str]:
    """Fill fwd_30d / fwd_90d (+ SPY excess) for entries old enough."""
    import yfinance as yf

    notes: list[str] = []
    today = date.today()
    spy_cache: dict[tuple[str, str], float | None] = {}

    def px_on_or_after(ticker: str, d: date) -> float | None:
        key = (ticker, d.isoformat())
        if key in spy_cache:
            return spy_cache[key]
        try:
            hist = yf.Ticker(ticker).history(
                start=d.isoformat(), end=(d + timedelta(days=10)).isoformat()
            )
            val = float(hist["Close"].iloc[0]) if len(hist) else None
        except Exception:
            val = None
        spy_cache[key] = val
        return val

    for e in ledger["entries"]:
        flag_d = date.fromisoformat(e["flag_date"])
        p0 = e.get("price_at_flag")
        if not p0:
            continue
        for horizon, field in ((30, "fwd_30d_pct"), (90, "fwd_90d_pct")):
            if e.get(field) is not None:
                continue
            target = flag_d + timedelta(days=horizon)
            if today < target + timedelta(days=2):
                continue
            p1 = px_on_or_after(e["ticker"], target)
            s0 = px_on_or_after("SPY", flag_d)
            s1 = px_on_or_after("SPY", target)
            if p1 is None:
                notes.append(f"backfill: no price for {e['ticker']} at +{horizon}d")
                continue
            e[field] = round((p1 / p0 - 1) * 100, 2)
            if s0 and s1:
                e[field.replace("pct", "excess_pct")] = round(
                    (p1 / p0 - s1 / s0) * 100, 2
                )
            notes.append(f"backfill: {e['ticker']} +{horizon}d = {e[field]}%")
    return notes


# ---- Fetch + classify -----------------------------------------------------


def fetch_profile(ticker: str) -> dict:
    """yfinance info subset: quoteType + listing age. Non-fatal on failure."""
    import yfinance as yf

    try:
        info = yf.Ticker(ticker).get_info()
    except Exception:
        return {}
    out = {}
    if info.get("quoteType"):
        out["quote_type"] = str(info["quoteType"]).upper()
    epoch = info.get("firstTradeDateEpochUtc") or info.get("firstTradeDateMilliseconds")
    if epoch:
        if abs(epoch) > 10**10:  # milliseconds (1972 in ms is ~6.3e10)
            epoch = epoch / 1000
        out["listed_days"] = (datetime.now() - datetime.fromtimestamp(epoch)).days
    if info.get("totalCash") is not None:
        out["total_cash"] = info["totalCash"]
    if info.get("totalDebt") is not None:
        out["total_debt"] = info["totalDebt"]
    if info.get("averageVolume") is not None:
        out["avg_volume"] = info["averageVolume"]
    return out


def classify(entry: dict, fund, profile: dict, held: bool, thesis: dict | None) -> tuple[str, str]:
    """Return (lane, reason). Lanes: holdings / value / spec / auto_skip / unresolved."""
    if held or thesis:
        return "holdings", "live position" if held else f"thesis on file ({thesis.get('status')})"
    no_data = fund is None or (fund.last_close is None and fund.market_cap is None)
    if no_data and not profile:
        return "unresolved", "yfinance could not resolve ticker"
    qt = profile.get("quote_type", "EQUITY")
    if qt in FUND_QUOTE_TYPES:
        return "auto_skip", f"fund/ETF (quoteType {qt}) — outside single-name universe"
    name = (entry.get("company") or "").lower()
    if re.search(r"\bfund\b|\betf\b|\btrust\b", name):
        return "auto_skip", "fund by name — outside single-name universe"
    listed = profile.get("listed_days")
    fresh = listed is not None and listed < FRESH_IPO_DAYS
    profitable = fund is not None and (
        (fund.profit_margin or 0) > 0 or (fund.trailing_pe or 0) > 0
    )
    big = fund is not None and (fund.market_cap or 0) > 5e9
    if profitable and big and not fresh:
        return "value", "profitable large-cap — 8-factor composite lane"
    reason = "unprofitable or small-cap — speculative checklist lane"
    if fresh:
        reason = f"fresh listing ({listed}d) — speculative checklist lane, limited filing history"
    return "spec", reason


def build_candidate(fund):
    from ai_buffett_zo.screener import Candidate

    mc = fund.market_cap
    fcf = fund.free_cash_flow
    pfcf = (mc / fcf) if (mc and fcf and fcf > 0) else None
    de = fund.debt_to_equity
    if de is not None and de > 5:  # yfinance reports percent
        de = de / 100
    return Candidate(
        ticker=fund.ticker,
        company=fund.company,
        sector=None,
        pe=fund.trailing_pe,
        pfcf=pfcf,
        roe=fund.return_on_equity,
        roic=None,
        op_margin=fund.operating_margin,
        profit_margin=fund.profit_margin,
        de=de,
        insider_pct=None,
        market_cap=mc,
        price=fund.last_close,
    )


def gate_clearing_entry(cand, t) -> dict | None:
    """QUALITY-WATCH check: passes every quality gate on present data (missing
    quality data disqualifies — 'unknown' is not 'good'), fails only the
    valuation gates. Returns the price at which P/E and P/FCF would both clear
    the regime bar at current trailing fundamentals, plus which gate binds.

    This is a mechanical screen anchor, NOT a fair value — trailing EPS/FCF can
    be cyclically depressed (capex cycles crush P/FCF), so the real add zone is
    assigned by the deep dive, not by this number."""
    if cand.price is None or cand.price <= 0:
        return None
    quality_ok = (
        cand.roe is not None and cand.roe * 100 >= t.roe_min_pct
        and cand.op_margin is not None and cand.op_margin * 100 >= t.op_margin_min_pct
        and cand.de is not None and cand.de <= t.de_max
    )
    if not quality_ok:
        return None
    val_fail = (cand.pe is not None and cand.pe > t.pe_max) or (
        cand.pfcf is not None and cand.pfcf > t.pfcf_max
    )
    if not val_fail:
        return None
    targets = {}
    if cand.pe is not None and cand.pe > 0:
        targets["P/E"] = cand.price * t.pe_max / cand.pe
    if cand.pfcf is not None and cand.pfcf > 0:
        targets["P/FCF"] = cand.price * t.pfcf_max / cand.pfcf
    if not targets:
        return None
    binding = min(targets, key=targets.get)
    return {
        "entry": round(targets[binding], 2),
        "binding": binding,
        "pct_below": round((targets[binding] / cand.price - 1) * 100, 1),
    }


def resolve_regime():
    try:
        from datetime import timedelta as td

        from ai_buffett_zo.data import EquityStore
        from ai_buffett_zo.regime import snapshot

        store = EquityStore()
        spy = store.history("SPY", max_age=td(hours=24))
        tlt = store.history("TLT", max_age=td(hours=24))
        rsp = store.history("RSP", max_age=td(hours=24))
        return snapshot(spy, tlt, rsp)
    except Exception as exc:
        print(f"_warning: regime unavailable ({exc}); continuing without", file=sys.stderr)
        return None


# ---- Formatting -----------------------------------------------------------


def fmt(v, pct=False, money=False) -> str:
    if v is None:
        return "—"
    if money:
        if abs(v) >= 1e12:
            return f"${v / 1e12:.2f}T"
        if abs(v) >= 1e9:
            return f"${v / 1e9:.1f}B"
        return f"${v / 1e6:.0f}M"
    if pct:
        return f"{v * 100:.1f}%" if abs(v) <= 1.5 else f"{v:.1f}%"
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def signals_line(entry: dict) -> str:
    return "; ".join(entry.get("signals", [])) or "—"


# ---- Main run -------------------------------------------------------------


def run(args) -> int:
    from ai_buffett_zo.evaluation import fetch_fundamentals
    from ai_buffett_zo.screener import score_and_rank, thresholds_for

    blob = json.loads(Path(args.input).read_text())
    snap_date = blob["snapshot_date"]
    entries: dict[str, dict] = {}
    for raw in blob["entries"]:
        t = raw["ticker"].upper()
        if t in entries:
            entries[t]["sections"].append(raw["section"])
            entries[t]["signals"].extend(raw.get("signals", []))
        else:
            entries[t] = {**raw, "sections": [raw["section"]], "signals": list(raw.get("signals", []))}

    theses = load_theses()
    positions = load_positions()
    wl_name, wl_tickers = load_watchlist_tickers()
    ledger = load_ledger()
    prior_flags: dict[str, list[dict]] = {}
    for e in ledger["entries"]:
        prior_flags.setdefault(e["ticker"], []).append(e)

    regime = resolve_regime()
    regime_color = getattr(regime, "color", None) or "orange"

    rows = []
    for t, entry in entries.items():
        fund = None
        try:
            fund = fetch_fundamentals(t)
        except Exception:
            pass
        held = t in positions
        thesis = theses.get(t)
        profile = {} if held or thesis else fetch_profile(t)
        lane, reason = classify(entry, fund, profile, held, thesis)
        rows.append(
            {
                "ticker": t,
                "entry": entry,
                "fund": fund,
                "profile": profile,
                "position": positions.get(t),
                "thesis": thesis,
                "on_watchlist": t in wl_tickers,
                "prior": prior_flags.get(t, []),
                "lane": lane,
                "reason": reason,
            }
        )

    # Composite for value lane
    value_rows = [r for r in rows if r["lane"] == "value" and r["fund"] is not None]
    scored = {}
    if value_rows:
        result = score_and_rank(
            [build_candidate(r["fund"]) for r in value_rows], regime_color=regime_color
        )
        scored = {s.candidate.ticker: s for s in result}

    # Suggested verdicts
    thresh = thresholds_for(regime_color)
    for r in rows:
        r["gate_entry"] = None
        if r["lane"] == "holdings":
            r["suggested"] = "HOLDINGS-SIGNAL"
        elif r["lane"] == "value":
            s = scored.get(r["ticker"])
            gate = gate_clearing_entry(build_candidate(r["fund"]), thresh) if r["fund"] else None
            if s and s.passed_threshold:
                r["suggested"] = "DEEP-DIVE"
            elif gate:
                r["suggested"] = "QUALITY-WATCH"
                r["gate_entry"] = gate
            elif s and s.composite >= 50:
                r["suggested"] = "WATCHLIST"
            else:
                r["suggested"] = "SKIP"
        elif r["lane"] == "spec":
            r["suggested"] = "SPEC-REVIEW"
        else:
            r["suggested"] = "SKIP"

    # Ledger append (idempotent per flag_date+ticker; same-date reruns refresh
    # the suggested verdict + gate entry so rule changes reach the ledger)
    by_key = {(e["flag_date"], e["ticker"]): e for e in ledger["entries"]}
    added = updated = 0
    for r in rows:
        key = (snap_date, r["ticker"])
        gate = r.get("gate_entry")
        if key in by_key:
            e = by_key[key]
            if e.get("suggested_verdict") != r["suggested"] or e.get("gate_entry") != gate:
                e["suggested_verdict"] = r["suggested"]
                e["gate_entry"] = gate
                updated += 1
            continue
        fund = r["fund"]
        ledger["entries"].append(
            {
                "flag_date": snap_date,
                "ticker": r["ticker"],
                "sections": r["entry"]["sections"],
                "signals": signals_line(r["entry"]),
                "price_at_flag": getattr(fund, "last_close", None),
                "lane": r["lane"],
                "suggested_verdict": r["suggested"],
                "gate_entry": gate,
                "final_verdict": None,
                "fwd_30d_pct": None,
                "fwd_30d_excess_pct": None,
                "fwd_90d_pct": None,
                "fwd_90d_excess_pct": None,
            }
        )
        added += 1
    backfill_notes = backfill_forward_returns(ledger)
    save_ledger(ledger)

    report_path = UPSIDE_ROOT / f"{snap_date}-vet.md"
    if report_path.exists() and not getattr(args, "force_report", False):
        print(f"report exists, NOT overwritten (finalized reports are precious; "
              f"rerun with --force-report to regenerate): {report_path}")
    else:
        report_path.write_text(render_report(snap_date, regime, rows, scored, ledger, wl_name))
        print(f"report: {report_path}")
    print(f"ledger: +{added} entries, {updated} refreshed ({len(ledger['entries'])} total)")
    for n in backfill_notes:
        print(n)
    for r in rows:
        print(f"{r['ticker']:6s} {r['lane']:10s} {r['suggested']:15s} {r['reason']}")
    return 0


def render_report(snap_date, regime, rows, scored, ledger, wl_name) -> str:
    regime_line = "regime unavailable — rerun clarion-regime-check"
    if regime is not None:
        danger = " · DANGER" if getattr(regime, "danger_state", False) else ""
        regime_line = f"{regime.color.upper()}{danger}"

    def by_lane(lane):
        return [r for r in rows if r["lane"] == lane]

    L = []
    L.append(f"# Upside vet — panel snapshot {snap_date}\n")
    L.append(f"*Generated {date.today().isoformat()} · regime: {regime_line} · "
             f"watchlist cross-ref: {wl_name or 'none'}*\n")
    L.append("Signal source: Upside Invest holdership movers (linked-portfolio panel; "
             "holder counts are net position adds/removes, not volume). "
             "Panel behavior is sentiment evidence, never thesis evidence.\n")

    hold = by_lane("holdings")
    L.append("## Holdings signals — read first\n")
    if hold:
        L.append("| Ticker | Panel signal | Our position | Thesis | Read |")
        L.append("|---|---|---|---|---|")
        for r in hold:
            p = r["position"]
            pos = (
                f"{p['quantity']:g} @ {p['cost_basis']:.2f} ({p['unrealized_pl_pct']:+.1f}%)"
                if p
                else "no position"
            )
            th = r["thesis"]
            thx = f"{th.get('status')}/{th.get('bucket')}" if th else "—"
            L.append(f"| **{r['ticker']}** | {signals_line(r['entry'])} | {pos} | {thx} | [AGENT] |")
    else:
        L.append("*None of the flagged names touch the book this run.*")
    L.append("")

    val = by_lane("value")
    L.append("## Value lane — 8-factor composite\n")
    if val:
        L.append("| Ticker | Composite | Passed | Weight | P/E | Op margin | Mkt cap | Gate entry | Suggested | Final |")
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        for r in sorted(val, key=lambda r: -(scored[r["ticker"]].composite if r["ticker"] in scored else 0)):
            s = scored.get(r["ticker"])
            f_ = r["fund"]
            g = r.get("gate_entry")
            gate_cell = f"${g['entry']:.2f} ({g['pct_below']:+.0f}%, {g['binding']} binds)" if g else "—"
            L.append(
                f"| {r['ticker']} | {s.composite:.0f} | {'Y' if s.passed_threshold else 'N'} | "
                f"{s.contributing_weight:.0f} | {fmt(f_.trailing_pe)} | {fmt(f_.operating_margin, pct=True)} | "
                f"{fmt(f_.market_cap, money=True)} | {gate_cell} | {r['suggested']} | [AGENT] |"
            )
        if any(r.get("gate_entry") for r in val):
            L.append("")
            L.append("**QUALITY-WATCH** = passes every quality gate (ROE, op margin, D/E), fails "
                     "only on valuation. *Gate entry* is the price at which P/E and P/FCF would "
                     "both clear the current regime's bar at trailing fundamentals — a mechanical "
                     "screen anchor, not a fair value. Trailing FCF can be cyclically depressed "
                     "(capex cycles), so the deep dive assigns the real add zone; the gate entry "
                     "just tells you when the name is worth that work.")
    else:
        L.append("*No value-lane candidates this run.*")
    L.append("")

    spec = by_lane("spec")
    L.append("## Speculative lane — YOLO checklist\n")
    L.append("Checklist (all must pass for a YOLO position; max 3% NLV each, 10% bucket total):\n"
             "1. Downside survivable — balance sheet funds the story (cash vs burn)\n"
             "2. Asymmetry statable in two sentences with a concrete catalyst\n"
             "3. Sizing fits the YOLO bucket alongside existing spec positions\n"
             "4. Liquidity sane (can exit in <5 sessions)\n"
             "5. Verifiable — filings exist; no filings, no position\n")
    if spec:
        L.append("| Ticker | Panel signal | Mkt cap | Cash | Debt | FCF | Listed | Checklist | Final |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for r in spec:
            f_ = r["fund"]
            pr = r["profile"]
            listed = f"{pr['listed_days']}d" if pr.get("listed_days") is not None else "—"
            L.append(
                f"| {r['ticker']} | {signals_line(r['entry'])} | "
                f"{fmt(getattr(f_, 'market_cap', None), money=True)} | {fmt(pr.get('total_cash'), money=True)} | "
                f"{fmt(pr.get('total_debt'), money=True)} | {fmt(getattr(f_, 'free_cash_flow', None), money=True)} | "
                f"{listed} | [AGENT 1-5] | [AGENT] |"
            )
    else:
        L.append("*No speculative-lane candidates this run.*")
    L.append("")

    skips = by_lane("auto_skip") + by_lane("unresolved")
    L.append("## Auto-skips\n")
    if skips:
        for r in skips:
            L.append(f"- **{r['ticker']}** — {r['reason']}")
    else:
        L.append("*None.*")
    L.append("")

    L.append("## Read-through for the book\n")
    L.append("[AGENT — 3-6 sentences: what this panel snapshot says about our positioning, "
             "which signals matter, which are noise.]\n")

    L.append("## Signal track record\n")
    matured = [e for e in ledger["entries"] if e.get("fwd_30d_pct") is not None]
    L.append(f"Ledger: {len(ledger['entries'])} flags · {len(matured)} matured to 30d+\n")
    if matured:
        L.append("| Flagged | Ticker | Sections | +30d | vs SPY | +90d | vs SPY |")
        L.append("|---|---|---|---|---|---|---|")
        for e in sorted(matured, key=lambda e: e["flag_date"], reverse=True)[:25]:
            L.append(
                f"| {e['flag_date']} | {e['ticker']} | {','.join(e['sections'])} | "
                f"{e['fwd_30d_pct']:+.1f}% | {fmt(e.get('fwd_30d_excess_pct'), pct=True)} | "
                f"{e['fwd_90d_pct']:+.1f}% | {fmt(e.get('fwd_90d_excess_pct'), pct=True)} |"
                if e.get("fwd_90d_pct") is not None
                else f"| {e['flag_date']} | {e['ticker']} | {','.join(e['sections'])} | "
                f"{e['fwd_30d_pct']:+.1f}% | {fmt(e.get('fwd_30d_excess_pct'), pct=True)} | — | — |"
            )
    else:
        L.append("*No matured entries yet — forward returns backfill automatically on later runs.*")
    L.append("")
    L.append("---\n")
    L.append("Jing Xie · Founder and President, Clarion Intelligence Systems\n")
    return "\n".join(L)


# ---- Subcommands ----------------------------------------------------------


def set_verdict(args) -> int:
    ledger = load_ledger()
    verdict = args.verdict.upper()
    if verdict not in VERDICTS:
        print(f"VET_ERROR: verdict must be one of {VERDICTS}")
        return 1
    hits = [
        e
        for e in ledger["entries"]
        if e["ticker"] == args.ticker.upper() and (not args.date or e["flag_date"] == args.date)
    ]
    if not hits:
        print(f"VET_ERROR: no ledger entry for {args.ticker} {args.date or ''}")
        return 1
    for e in hits[-1:]:
        e["final_verdict"] = verdict
        print(f"set {e['ticker']} {e['flag_date']} final_verdict={verdict}")
    save_ledger(ledger)
    return 0


def track_record(args) -> int:
    ledger = load_ledger()
    notes = backfill_forward_returns(ledger)
    save_ledger(ledger)
    for n in notes:
        print(n)
    entries = ledger["entries"]
    matured = [e for e in entries if e.get("fwd_30d_pct") is not None]
    print(f"{len(entries)} flags, {len(matured)} matured to 30d+")
    if matured:
        avg30 = sum(e["fwd_30d_pct"] for e in matured) / len(matured)
        ex = [e["fwd_30d_excess_pct"] for e in matured if e.get("fwd_30d_excess_pct") is not None]
        print(f"avg +30d: {avg30:+.2f}%" + (f" · avg excess vs SPY: {sum(ex) / len(ex):+.2f}%" if ex else ""))
    for e in sorted(entries, key=lambda e: e["flag_date"], reverse=True):
        print(
            f"{e['flag_date']} {e['ticker']:6s} {','.join(e['sections']):22s} "
            f"flag@{e['price_at_flag'] or '—'} 30d={e.get('fwd_30d_pct')} 90d={e.get('fwd_90d_pct')} "
            f"verdict={e.get('final_verdict') or e['suggested_verdict']}"
        )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")

    runp = sub.add_parser("run", help="Vet a parsed update (default command).")
    runp.add_argument("--input", required=True)
    runp.add_argument("--force-report", action="store_true",
                      help="Regenerate the report even if it already exists (clobbers finalized [AGENT] fills).")

    sv = sub.add_parser("set-verdict", help="Record the final verdict for a ledger entry.")
    sv.add_argument("ticker")
    sv.add_argument("verdict")
    sv.add_argument("--date", default=None)

    sub.add_parser("track-record", help="Backfill forward returns and print the ledger.")

    # Allow bare `vet.py --input x` without the `run` word
    argv = sys.argv[1:]
    if argv and argv[0].startswith("--"):
        argv = ["run"] + argv
    args = ap.parse_args(argv)

    if args.cmd == "run":
        return run(args)
    if args.cmd == "set-verdict":
        return set_verdict(args)
    if args.cmd == "track-record":
        return track_record(args)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
