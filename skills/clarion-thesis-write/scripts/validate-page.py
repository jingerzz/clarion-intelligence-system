#!/usr/bin/env python3
"""Validate a Zo Space thesis page before reporting it done.

Three layers, cheapest first:

  static  -- parse the route source. Proves every tab panel is reachable and
             that the tab machinery is actually declared. Milliseconds, no
             browser, belongs in every edit loop.

  render  -- load the page in a real browser and assert it does not throw,
             then click every tab and assert the panel content actually
             changes. This is the only layer that catches a page which is
             syntactically parseable but dead at runtime.

  live    -- alias for --render, kept for the older call sites.

Two bug classes motivated this file, both of which shipped to production:

  DECK, 2026-08-20 -- tab ids were derived from labels ("Core Thesis" ->
  "corethesis") while the render guards still used the template's literal ids
  ("thesis"). The default useState("thesis") matched its guard, so the panel
  painted on load and a screenshot looked perfect; clicking blanked it. Caught
  by the reachability check below.

  RDDT, 2026-08-20 -- the component referenced `tabs`, `setTab` and `tabStyle`
  without declaring any of them. The page threw "tabs is not defined" and
  rendered nothing but an error boundary. It had been dead on the public site
  for an unknown period. The previous version of this checker reported it as
  "tab shape unrecognized -- verify by hand" and it was filed under cosmetic.
  Caught now by the declaration check (static) and the error-boundary check
  (render).

A checker that cries wolf gets ignored, and an ignored checker is how RDDT
stayed dead. Every rule here is calibrated against all 43 production pages;
when a rule fires, it should mean something. Verified 2026-08-20: the only
true positive in the failure list was RDDT.

Usage
  validate-page.py --ticker DECK                  # static, one page
  validate-page.py --ticker DECK --render         # + real browser
  validate-page.py --all                          # static, every page
  validate-page.py --all --render                 # full sweep (slow, ~3s/page)
  validate-page.py --ticker DECK --verdict skip   # override page type

Exit code 0 = pass, 1 = fail. One line per check.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROUTES = Path("/__substrate/space/routes/pages")
BASE_URL = "http://localhost:3099"

# A page satisfies its "evidence" requirement with any of these. TCEHY is a
# Hong Kong filer and carries HKEX Evidence; TLT is a macro instrument and
# carries Macro Evidence; ETFs carry Top Holdings. Holding all of them to the
# literal string "SEC Evidence" produces permanent false failures.
EVIDENCE_ALIASES = ["SEC Evidence", "HKEX Evidence", "Macro Evidence",
                    "Top Holdings", "Filing Evidence"]
# Watchlist pages use either phrasing in production.
WAITING_ALIASES = ["Why I'm Waiting", "Why I'm Watching"]

# Each requirement is a list of acceptable alternatives.
REQUIRED_BY_VERDICT = {
    "addhold":   [["Core Thesis"], EVIDENCE_ALIASES, ["Valuation"],
                  ["Position Mgmt", "Position Management"], ["Screener"]],
    "skip":      [["Why I'm Passing"], EVIDENCE_ALIASES, ["Valuation"],
                  ["Revisit Triggers"]],
    "watchlist": [WAITING_ALIASES, EVIDENCE_ALIASES, ["Valuation"],
                  ["Revisit Triggers"]],
    # ETFs and macro instruments have no company screener and no 10-K.
    "etf":       [["Core Thesis"], EVIDENCE_ALIASES, ["Valuation"],
                  ["Position Mgmt", "Position Management"]],
    "macro":     [["Core Thesis"], EVIDENCE_ALIASES, ["Valuation"],
                  ["Position Mgmt", "Position Management"]],
    # Not a thesis page (slide deck, methodology doc, dynamic brief route,
    # draft). No section or brand contract — but still declaration-checked and
    # render-checked, and named in the sweep summary so the exemption is never
    # silent. A hardcoded skip-list was rejected here: it rots invisibly, and
    # an invisible exemption is the same failure class as a dead page filed
    # under "cosmetic".
    "other":     [],
}

THESIS_MARKERS = ["Core Thesis", "Why I'm Passing", "Top Holdings",
                  "Macro Evidence"] + WAITING_ALIASES


def detect_verdict(src):
    if "Why I'm Passing" in src:
        return "skip"
    if any(a in src for a in WAITING_ALIASES):
        return "watchlist"
    if "Top Holdings" in src:
        return "etf"
    if "Macro Evidence" in src:
        return "macro"
    if not any(m in src for m in THESIS_MARKERS):
        return "other"
    return "addhold"


class Result:
    def __init__(self):
        self.checks = []
        self.failed = False
        self.warned = False

    def add(self, ok, name, detail=""):
        self.checks.append(("PASS" if ok else "FAIL", name, detail))
        if not ok:
            self.failed = True

    def warn(self, name, detail=""):
        """Non-failing signal. Reserved for content-quality observations.

        A FAIL must always mean "this page is broken". Mixing "thin" in with
        "blank" is what trains people to skim the output, and a skimmed
        checker is indistinguishable from no checker.
        """
        self.checks.append(("WARN", name, detail))
        self.warned = True

    def report(self, header):
        print(f"\n=== {header} ===")
        for mark, name, detail in self.checks:
            line = f"  [{mark}] {name}"
            if detail:
                line += f" — {detail}"
            print(line)


def find_route(ticker):
    for cand in (ticker, ticker.upper(), ticker.lower()):
        p = ROUTES / f"{cand}.tsx"
        if p.exists():
            return p
    return None


def derive_id(label):
    return label.lower().replace(" ", "")


def brand_is_linked(src):
    """True if the nav brand text sits inside an <a> that points home.

    Deliberately not a single regex. The naive version
    `<a[^>]*href="..."[^>]*>\\s*Elendil Labs` produced six false failures:
    `[^>]*` stops at the `>` inside `onMouseEnter={e => ...}` (ADBE), and
    `>\\s*BRAND` misses a nested `<span>` wrapper (meta, NFLX) or a `‹ `
    back-arrow prefix (BABA, COIN, JD, TCEHY). All six were correctly linked.
    Instead: find the brand text, walk backwards, and check the nearest
    enclosing tag is an unclosed home-pointing anchor.
    """
    for brand in ("Clarion Intelligence Systems", "Elendil Labs"):
        for m in re.finditer(re.escape(brand), src):
            before = src[:m.start()]
            open_at = before.rfind("<a ")
            if open_at == -1:
                continue
            # An </a> between the anchor and the brand means we are outside it.
            if before.rfind("</a>") > open_at:
                continue
            tag = src[open_at:m.start()]
            if re.search(r'href="https://(?:cis\.zo\.space|elendillabs\.com)/?"', tag):
                return True
    return False


def declared_names(src):
    """Every identifier bound anywhere in the module or component body."""
    names = set()
    names |= set(re.findall(r'\bconst\s+(\w+)', src))
    names |= set(re.findall(r'\blet\s+(\w+)', src))
    names |= set(re.findall(r'\bfunction\s+(\w+)', src))
    for grp in re.findall(r'const\s*\[([^\]]+)\]\s*=', src):
        names |= {n.strip() for n in grp.split(",") if n.strip()}
    for grp in re.findall(r'const\s*\{([^}]+)\}\s*=', src):
        names |= {n.split(":")[-1].strip() for n in grp.split(",") if n.strip()}
    names |= set(re.findall(r'import\s+\{([^}]*)\}', src)[0].split(",")) \
        if re.findall(r'import\s+\{([^}]*)\}', src) else set()
    return {n.strip() for n in names}


def check_declarations(src, res):
    """Catch the RDDT class: tab machinery referenced but never declared.

    A React component that references an undefined name compiles fine and
    throws at render. This is the cheapest possible way to detect that.
    """
    declared = declared_names(src)
    used = set()
    for name in ("tabs", "tabStyle", "setTab", "tab"):
        if re.search(r'(?<![\w.])' + name + r'(?![\w])', src):
            used.add(name)
    missing = sorted(n for n in used if n not in declared)
    res.add(not missing, "tab machinery is declared",
            f"referenced but never declared: {missing} — PAGE WILL THROW AT RENDER"
            if missing else "")
    return not missing


def find_tab_state(src):
    """Return (state_var, initial, is_numeric) for the tab state."""
    for var, setter, initial in re.findall(
            r'const\s*\[\s*(\w+)\s*,\s*(\w+)\s*\]\s*=\s*useState\s*'
            r'(?:<[^>]*>)?\s*\(\s*"([^"]*)"\s*\)', src):
        if "tab" in setter.lower():
            return var, initial, False
    # Numeric-index tabs (SYF): useState(0) + setTab(i) + `tab === 0`.
    for var, setter, initial in re.findall(
            r'const\s*\[\s*(\w+)\s*,\s*(\w+)\s*\]\s*=\s*useState\s*'
            r'(?:<[^>]*>)?\s*\(\s*(\d+)\s*\)', src):
        if "tab" in setter.lower():
            return var, initial, True
    return None, None, False


def static_check(path, verdict, res):
    src = path.read_text()

    if not check_declarations(src, res):
        return

    if "setTab" not in src:
        res.add(True, "no tab bar on this page", "single-panel layout")
    else:
        state_var, initial, numeric = find_tab_state(src)
        if not state_var:
            res.add(False, "tab state variable located",
                    "found setTab but no matching useState declaration")
            return
        check_tabs(src, state_var, initial, numeric, res)

    if verdict == "other":
        res.add(True, "not a thesis page",
                "no section or brand contract enforced")
        return

    required = REQUIRED_BY_VERDICT[verdict]
    missing = [alts for alts in required if not any(a in src for a in alts)]
    res.add(not missing, f"required {verdict} sections present",
            f"missing: {[a[0] for a in missing]}" if missing
            else f"{len(required)}/{len(required)}")

    linked = brand_is_linked(src)
    res.add(linked, "nav brand links back",
            "" if linked else "brand text in nav is not inside a home-pointing anchor")


def check_tabs(src, state_var, initial, numeric, res):
    if numeric:
        # Index-based tabs cannot suffer id drift; verify the count lines up.
        guards = set(re.findall(re.escape(state_var) + r'\s*===\s*(\d+)', src))
        m = re.search(r'const\s+tabs\s*(?::[^=]*)?=\s*\[([^\]]*)\]', src)
        labels = re.findall(r'"([^"]+)"', m.group(1)) if m else []
        emitted = {str(i) for i in range(len(labels))}
        res.add(True, "tab bar shape recognized", "D: numeric index")
        res.add(bool(guards), "tab guards found",
                f'state var "{state_var}", {len(guards)} panels: {sorted(guards, key=int)}')
        orphan = emitted - guards
        res.add(not orphan, "every tab reaches a panel",
                f"UNREACHABLE PANEL for tab index/indices: {sorted(orphan)}" if orphan else "")
        dead = guards - emitted
        res.add(not dead, "every panel is reachable from a tab",
                f"dead panel guard(s): {sorted(dead)}" if dead else "")
        res.add(initial in guards, "default tab renders on load",
                "" if initial in guards else f"useState({initial}) matches no panel")
        return

    guards = set(re.findall(re.escape(state_var) + r'\s*===\s*"([^"]+)"', src))
    res.add(bool(guards), "tab guards found",
            f'state var "{state_var}", {len(guards)} panels: {sorted(guards)}')
    if not guards:
        return

    emitted, pattern = set(), None

    m = re.search(r'const\s+tabs\s*:\s*\[string,\s*string\]\[\]\s*=\s*\[(.*?)\]\s*;', src, re.S)
    if m:
        emitted = {pid for pid, _ in
                   re.findall(r'\[\s*"([^"]+)"\s*,\s*"([^"]*)"\s*\]', m.group(1))}
        pattern = "C: (id,label) tuples"

    if pattern is None:
        m = re.search(r'const\s+tabs\s*=\s*\[([^\]]*)\]', src)
        if m:
            labels = re.findall(r'"([^"]+)"', m.group(1))
            derived = re.search(r'toLowerCase\(\)\.replace\(\s*/ /g', src)
            emitted = {derive_id(l) for l in labels} if derived else set(labels)
            pattern = "A: labels + derived ids" if derived else "B: explicit ids"

    if pattern is None:
        m = re.search(r'\(\s*\[((?:\s*"[^"]+"\s*,?)+)\]\s*as\s+const\s*\)', src)
        if m:
            emitted = set(re.findall(r'"([^"]+)"', m.group(1)))
            pattern = "B: explicit ids (as const)"

    if pattern is None:
        res.add(False, "tab bar shape recognized",
                "could not parse the tab list; run --render on this page")
        return

    res.add(True, "tab bar shape recognized", pattern)

    alias_groups = [set(re.findall(r'"([^"]+)"', chain))
                    for chain in re.findall(
                        re.escape(state_var) + r'\s*===\s*"[^"]+"(?:\s*\|\|\s*'
                        + re.escape(state_var) + r'\s*===\s*"[^"]+")+', src)]
    reachable, covered = set(emitted), set(guards)
    for grp in alias_groups:
        if grp & emitted:
            reachable |= grp
            covered -= grp
    if alias_groups:
        res.add(True, "legacy tab aliases honored", f"{[sorted(g) for g in alias_groups]}")

    orphan_tabs = emitted - guards
    orphan_panels = covered - reachable
    res.add(not orphan_tabs, "every tab reaches a panel",
            f"UNREACHABLE PANEL for tab id(s): {sorted(orphan_tabs)}" if orphan_tabs else "")
    res.add(not orphan_panels, "every panel is reachable from a tab",
            f"dead panel guard(s): {sorted(orphan_panels)}" if orphan_panels else "")

    ok_render = initial in guards
    res.add(ok_render, "default tab renders on load",
            "" if ok_render else f'useState("{initial}") matches no panel — loads blank')
    ok_select = initial in reachable
    res.add(ok_select, "default tab is re-selectable",
            "" if ok_select else
            f'"{initial}" renders on load but no tab button emits it — clicking blanks it')


# --------------------------------------------------------------------------
# Render layer
# --------------------------------------------------------------------------

# agent-browser `snapshot` serves a cached accessibility tree that does not
# always reflect post-click state; it reported four identical panels on a page
# whose tabs were in fact working. `eval` reads the live DOM. Use eval only.
# Panel content is measured by stripping the chrome — the text prefix and
# suffix common to every tab (nav, header, stats bar, tab row, sources,
# footer). What remains is the panel itself. A raw body-length threshold was
# tried first and rejected: it flagged SYF, whose five panels are legitimately
# terse, while a page whose chrome is heavy could hide a truly blank panel
# above the same threshold. Absolute length says nothing; panel-specific
# length says everything.
PROBE_JS = """
(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const err = document.body.innerText.includes("Something went wrong")
           || document.body.innerText.includes("encountered an error while rendering");
  if (__SKIP_TABS__) {
    return JSON.stringify({ threw: err, bodyLen: document.body.innerText.length,
                            chrome: 0, tabs: [] });
  }
  const btns = Array.from(document.querySelectorAll("button"))
                    .filter(b => b.textContent && b.textContent.trim()
                              && b.textContent !== "Reload page")
                    .slice(0, 12);
  const texts = [], labels = [];
  for (const b of btns) {
    const before = document.body.innerText;
    b.click();
    // Wait for the click to actually repaint instead of a fixed 450ms. On a
    // cold box (first sweep after boot, Chrome paging in through gVisor 9p)
    // 450ms was routinely shorter than the re-render, so every read captured
    // the pre-click body, every text came back identical, and the chrome
    // stripper reported all panels blank — the 2026-09-05 NVDA false alarm.
    // A page whose click genuinely does nothing still exits after 1400ms and
    // is caught by the identical-body check below, so detection is preserved.
    for (let waited = 0; waited < 1400; waited += 100) {
      await sleep(100);
      if (document.body.innerText !== before) break;
    }
    await sleep(120);
    labels.push(b.textContent.trim());
    texts.push(document.body.innerText);
  }
  let pre = 0, suf = 0;
  if (texts.length > 1) {
    const min = Math.min(...texts.map(t => t.length));
    while (pre < min && texts.every(t => t[pre] === texts[0][pre])) pre++;
    while (suf < min - pre &&
           texts.every(t => t[t.length - 1 - suf] === texts[0][texts[0].length - 1 - suf])) suf++;
  }
  const tabs = labels.map((l, i) => ({
    label: l,
    panel: texts[i].length - pre - suf,
    total: texts[i].length,
  }));
  return JSON.stringify({ threw: err, bodyLen: document.body.innerText.length,
                          chrome: pre + suf, tabs: tabs });
})()
"""

# A panel carrying fewer than this many characters unique to it did not render.
# The real DECK/RDDT failures rendered 0. SYF's Valuation panel renders 30
# ("BEAR $58 BASE $92 BULL $118") — thin, but present, so it warns not fails.
MIN_PANEL_CHARS = 25
THIN_PANEL_CHARS = 200


def render_check(ticker, res, skip_tabs=False):
    def ab(*args, timeout=90):
        # A TimeoutExpired here used to propagate and kill the whole sweep —
        # the "render sweep hung, cannot determine which page" incidents.
        # One stalled page must cost one page, not the run.
        try:
            return subprocess.run(["agent-browser", *args], capture_output=True,
                                  text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    r = ab("open", f"{BASE_URL}/{ticker}")
    if r is None:
        res.add(False, "page loads", f"agent-browser stalled >90s opening /{ticker}")
        return
    if r.returncode != 0:
        res.add(False, "page loads", r.stderr.strip()[:200])
        return

    # Fixed sleep(3) assumed a warm box. The first sweep of the day pays
    # Chrome cold-start plus Vite first-request transforms and can need far
    # longer. Poll until the body stops changing (two stable reads) instead.
    last = -1
    for _ in range(8):
        time.sleep(1.2)
        e = ab("eval", "document.body.innerText.length", timeout=30)
        if e is None:
            continue
        try:
            n = int(e.stdout.strip())
        except ValueError:
            n = -2
        if n > 0 and n == last:
            break
        last = n

    probe = PROBE_JS.replace("__SKIP_TABS__", "true" if skip_tabs else "false")
    er = ab("eval", probe.strip(), timeout=120)
    if er is None:
        res.add(False, "render probe returned data",
                f"probe stalled >120s on /{ticker} — browser or page wedged")
        return
    raw = er.stdout.strip()
    m = re.search(r'\{.*\}', raw.replace('\\"', '"'))
    if not m:
        res.add(False, "render probe returned data", raw[:200])
        return
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        res.add(False, "render probe returned data", raw[:200])
        return

    res.add(not data["threw"], "page renders without throwing",
            "ERROR BOUNDARY — page is dead" if data["threw"] else
            f"{data['bodyLen']} chars")
    if data["threw"]:
        return

    tabs = data["tabs"]
    if skip_tabs:
        # Non-thesis pages (letter, ledger, glossary, slide decks) have buttons
        # that are controls, not tabs. Exercising them produces noise. The
        # error-boundary assertion above is the check that matters for them —
        # and it is the one that would have caught RDDT.
        res.add(True, "tab content not checked", "non-thesis page")
        return

    if len(tabs) < 2:
        # One button is a control (fullscreen, reload), not a tab bar.
        res.add(True, "no tab bar to exercise",
                "single-panel layout" if not tabs else
                f"one button only ({tabs[0]['label']}) — not a tab bar")
        return

    empty = [t["label"] for t in tabs if t["panel"] < MIN_PANEL_CHARS]
    res.add(not empty, "every tab paints content",
            f"EMPTY PANEL(S): {empty}" if empty else
            " · ".join(f"{t['label']}={t['panel']}" for t in tabs))
    thin = [f"{t['label']}={t['panel']}" for t in tabs
            if MIN_PANEL_CHARS <= t["panel"] < THIN_PANEL_CHARS]
    if thin:
        res.warn("panel content is thin", ", ".join(thin) + " chars — renders, but sparse")

    # Identical bodies across every tab means clicks are not switching panels.
    stuck = len({t["total"] for t in tabs}) == 1
    res.add(not stuck, "tabs actually switch panels",
            "every tab renders an identical body — panel does not change" if stuck else "")


def render_check_verified(ticker, res, skip_tabs=False):
    """render_check, but a failure must reproduce before it is reported.

    Every render false alarm so far (NVDA 2026-09-05, the RDDT-era sweep
    hangs) was a first-probe timing artifact, while every real dead page
    fails deterministically. One retry after a settle costs 10s on a broken
    page and nothing on a healthy one, and it converts "SMS Jing at 7am
    about a page that is fine" into silence. A pass-on-retry is surfaced as
    a WARN so a chronically flaky page still leaves a trace.
    """
    first = Result()
    render_check(ticker, first, skip_tabs)
    if not first.failed:
        res.checks += first.checks
        res.warned |= first.warned
        return
    time.sleep(5)
    second = Result()
    render_check(ticker, second, skip_tabs)
    res.checks += second.checks
    res.failed |= second.failed
    res.warned |= second.warned
    if not second.failed:
        res.warn("render flaked on first probe, passed on retry",
                 "; ".join(n for m, n, _ in first.checks if m == "FAIL"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--render", action="store_true", help="drive a real browser")
    ap.add_argument("--live", action="store_true", help="alias for --render")
    ap.add_argument("--verdict", default=None,
                    choices=["addhold", "skip", "etf", "watchlist", "macro"])
    ap.add_argument("--routes-dir")
    ap.add_argument("--quiet-if-clean", action="store_true",
                    help="print nothing when everything passes (for cron/automation)")
    args = ap.parse_args()
    do_render = args.render or args.live
    quiet = args.quiet_if_clean

    if args.routes_dir:
        global ROUTES
        ROUTES = Path(args.routes_dir)
    if not args.all and not args.ticker:
        ap.error("pass --ticker TICKER or --all")

    if args.all:
        # These are not thesis pages, so no section/brand/tab contract applies.
        # They are NOT excluded from the sweep: they still get the declaration
        # and error-boundary checks. Excluding a route from the sweep entirely
        # is how a page dies unnoticed, which is the whole reason this file
        # was rewritten.
        non_thesis = {"_home", "index", "glossary", "letter", "ledger", "welcome",
                      "talk", "sp500", "situational-awareness", "elendil-preview"}
        paths = sorted(ROUTES.glob("*.tsx"))
        if not quiet:
            print(f"Checking {len(paths)} routes"
                  f"{' (static + render)' if do_render else ' (static)'}...")
        failures, exempt, warned = [], [], []
        for p in paths:
            res = Result()
            verdict = "other" if p.stem in non_thesis else detect_verdict(p.read_text())
            if verdict == "other":
                exempt.append(p.stem)
            static_check(p, verdict, res)
            if do_render:
                render_check_verified(p.stem.lower(), res, skip_tabs=(verdict == "other"))
            if (res.failed or res.warned) and not quiet:
                res.report(f"{p.stem}  ({verdict})")
            if res.failed:
                if quiet:
                    res.report(f"{p.stem}  ({verdict})")
                failures.append(p.stem)
            elif res.warned:
                warned.append(p.stem)
        if quiet:
            if failures:
                print(f"\n{len(failures)} BROKEN PAGE(S): {', '.join(failures)}")
            return 1 if failures else 0
        print(f"\n{len(paths) - len(failures)}/{len(paths)} pages clean.")
        if exempt:
            print(f"Section/brand checks not applicable (non-thesis pages): "
                  f"{', '.join(exempt)}")
        if warned:
            print(f"WARN (renders, but thin): {', '.join(warned)}")
        if failures:
            print(f"FAILED: {', '.join(failures)}")
        return 1 if failures else 0

    path = find_route(args.ticker)
    if not path:
        print(f"No route source for {args.ticker} at {ROUTES}")
        return 1

    verdict = args.verdict or detect_verdict(path.read_text())
    res = Result()
    static_check(path, verdict, res)
    if do_render:
        render_check_verified(args.ticker.lower(), res)
    res.report(f"{args.ticker}  ({verdict})")
    print("\nRESULT:", "FAIL" if res.failed else
          ("PASS (with warnings)" if res.warned else "PASS"))
    return 1 if res.failed else 0


if __name__ == "__main__":
    sys.exit(main())
