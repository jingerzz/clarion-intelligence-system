"""Render and lightly parse watchlist markdown files.

Output format mirrors the watchlist files in ai-buffett/watchlists/
(per-screen markdown with Context, Stage 1 ranked table, Top-N after sector
cap, Sniff Test scaffold for the chat agent to fill, Passed-on, Existing
Theses Impact).

The parse half is intentionally lightweight — it only extracts what
clarion-watchlist-update needs to surface trigger hits and diff vs the
prior screen (ticker + score + sector + price). Prose round-trip is not
attempted.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ai_buffett_zo.screener.types import (
    ScoredCandidate,
    ScreenContext,
    SectorCapResult,
)

DEFAULT_WATCHLIST_ROOT = Path.home() / "clarion" / "watchlists"


# ---- Render ---------------------------------------------------------------


def watchlist_path(root: Path, screen_date: date) -> Path:
    return root / f"sp500-screen-{screen_date.isoformat()}.md"


def render_watchlist(
    *,
    context: ScreenContext,
    ranked: list[ScoredCandidate],
    cap_result: SectorCapResult,
    notes_what_changed: str = "",
) -> str:
    """Render the full watchlist markdown.

    Stages 1 + 2 prose sections (Sniff Test, Passed On, Existing Theses Impact)
    are scaffolded with TODO markers — the chat agent fills these in.
    """
    parts: list[str] = []
    parts.append(f"# {context.universe} Value Screen — {context.screen_date.isoformat()}")
    parts.append("")
    parts.extend(_render_context_block(context))
    parts.append("")

    if notes_what_changed:
        parts.append("## What Changed Since Last Screen")
        parts.append("")
        parts.append(notes_what_changed)
        parts.append("")

    parts.append(f"## Stage 1 Ranked Results — Top {len(ranked)} (Raw Composite, Pre Sector Cap)")
    parts.append("")
    parts.append(
        "*v2 formula: P/E (15%) + P/FCF (15%) + ROE (15%) + ROIC (10%) + "
        "OpM (10%) + D/E (15%) + ProfitMargin (10%) + Insider (10%)*"
    )
    parts.append("")
    parts.append(_render_ranked_table(ranked))
    parts.append("")

    parts.append(f"## Top {len(cap_result.top)} After Sector Cap (Max 3 per GICS)")
    parts.append("")
    parts.append(_render_cap_table(cap_result))
    parts.append("")
    if cap_result.displaced:
        parts.extend(_render_displaced_notes(cap_result))
        parts.append("")

    parts.append("## Sniff Test: New Names Worth a Stage 2 Deep Dive")
    parts.append("")
    parts.append(
        "*[TODO] Strip out names already covered by an active thesis or prior screen. "
        "Group the remaining new names by sniff-test tier (Tier 1 = clear winners; "
        "Tier 2 = worth a look but flagged; Tier 3 = pass).*"
    )
    parts.append("")
    parts.append("### Tier 1 — Clear sniff-test winners")
    parts.append("")
    parts.append("[TODO Per-candidate snapshot — see the AWB watchlist examples for shape]")
    parts.append("")
    parts.append("### Tier 2 — Worth a look but flagged")
    parts.append("")
    parts.append("[TODO]")
    parts.append("")

    parts.append("## Passed On (Notable)")
    parts.append("")
    parts.append(
        "*[TODO] 2-3 sentences on interesting companies that didn't make the cut and why. "
        "This builds institutional memory — \"we looked at X but passed because Y\" is "
        "valuable for future screens.*"
    )
    parts.append("")

    parts.append("## Existing Theses Impact")
    parts.append("")
    parts.append(
        "*[TODO] Did this screen surface any companies where you already have an active "
        "thesis? If so, does the screening data change your view?*"
    )
    parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def _render_context_block(c: ScreenContext) -> list[str]:
    out = [
        "## Context",
        "",
        f"- **Regime**: {c.regime_color.upper()}{' (DANGER state)' if c.danger_state else ''}",
    ]
    if c.rf_rate_pct is not None and c.hurdle_rate_pct is not None:
        out.append(
            f"- **Hurdle Rate**: {c.hurdle_rate_pct:.2f}% "
            f"({c.rf_rate_pct:.2f}% rf + regime premium)"
        )
    elif c.rf_rate_pct is not None:
        out.append(f"- **Risk-Free Rate**: {c.rf_rate_pct:.2f}%")
    if c.sp500_cape is not None:
        cape_line = f"- **S&P 500 CAPE**: {c.sp500_cape:.1f}"
        if c.sp500_trailing_pe is not None:
            cape_line += f" (Trailing P/E: {c.sp500_trailing_pe:.1f})"
        out.append(cape_line)
    if c.implied_return_low_pct is not None and c.implied_return_high_pct is not None:
        out.append(
            f"- **Implied Equity Return (10y)**: "
            f"{c.implied_return_low_pct:.0f}–{c.implied_return_high_pct:.0f}%"
        )
    out.append(f"- **Screening Stance**: **{c.stance}**")
    out.append(f"- **Universe**: {c.universe}")
    if c.notes:
        out.append(f"- **Notes**: {c.notes}")
    return out


def _render_ranked_table(ranked: Iterable[ScoredCandidate]) -> str:
    headers = [
        "Rank", "Ticker", "Sector", "Score", "P/E", "P/FCF", "ROE%",
        "ROIC%", "OpM%", "D/E", "ProfM%", "Insider%", "Mkt Cap", "Price",
    ]
    rows: list[list[str]] = []
    for i, s in enumerate(ranked, start=1):
        c = s.candidate
        rows.append([
            str(i),
            c.ticker,
            c.sector,
            f"**{s.composite:.1f}**" if i == 1 else f"{s.composite:.1f}",
            _fmt_num(c.pe),
            _fmt_num(c.pfcf),
            _fmt_pct_decimal(c.roe),
            _fmt_pct_decimal(c.roic),
            _fmt_pct_decimal(c.op_margin),
            _fmt_num(c.de),
            _fmt_pct_decimal(c.profit_margin),
            _fmt_signed_pct(c.insider_pct),
            _fmt_money(c.market_cap),
            _fmt_money(c.price),
        ])
    return _markdown_table(headers, rows)


def _render_cap_table(result: SectorCapResult) -> str:
    headers = ["Rank", "Ticker", "Sector", "Score"]
    rows = []
    for i, s in enumerate(result.top, start=1):
        rows.append([str(i), s.candidate.ticker, s.candidate.sector, f"{s.composite:.1f}"])
    out = _markdown_table(headers, rows)
    if result.sectors_relaxed:
        out += (
            "\n\n*Sector cap relaxed to 4 per sector — fewer than 4 distinct sectors "
            "represented in the top 20 by raw score (the universe is genuinely "
            "concentrated in a few quality sectors).*"
        )
    return out


def _render_displaced_notes(result: SectorCapResult) -> list[str]:
    cap_displaced = [
        (s, reason) for s, reason in result.displaced if "sector cap" in reason
    ]
    if not cap_displaced:
        return []
    bullets = [
        f"- **{s.candidate.ticker}** ({s.candidate.sector}, score {s.composite:.1f}) — {reason}"
        for s, reason in cap_displaced
    ]
    return ["**Displaced by sector cap:**", "", *bullets]


# ---- Light parse (for clarion-watchlist-update) ---------------------------


@dataclass(frozen=True)
class WatchlistRow:
    """A row from the Stage 1 ranked table or the Top-After-Cap table."""

    rank: int
    ticker: str
    sector: str
    score: float
    price: float | None = None


def list_watchlists(root: Path = DEFAULT_WATCHLIST_ROOT) -> list[Path]:
    """Watchlist files sorted oldest-first by date in the filename."""
    if not root.exists():
        return []
    return sorted(root.glob("sp500-screen-*.md"))


def latest_watchlist(root: Path = DEFAULT_WATCHLIST_ROOT) -> Path | None:
    files = list_watchlists(root)
    return files[-1] if files else None


_RANKED_SECTION_RE = re.compile(
    r"## Stage 1 Ranked Results.*?(?=^## )",
    re.DOTALL | re.MULTILINE,
)


def parse_ranked_table(content: str) -> list[WatchlistRow]:
    """Pull the Stage 1 ranked table from a watchlist file."""
    m = _RANKED_SECTION_RE.search(content)
    if m is None:
        return []
    block = m.group(0)
    rows: list[WatchlistRow] = []
    for line in block.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        if cells[0].lower() == "rank" or set(cells[0]) <= {"-"}:
            continue  # header / dashes row
        try:
            rank = int(cells[0])
        except ValueError:
            continue
        ticker = cells[1]
        sector = cells[2]
        # Score may be wrapped in **bold**
        score_cell = cells[3].replace("*", "").strip()
        try:
            score = float(score_cell)
        except ValueError:
            continue
        price = _parse_money(cells[-1]) if len(cells) >= 14 else None
        rows.append(WatchlistRow(rank=rank, ticker=ticker, sector=sector, score=score, price=price))
    return rows


# ---- Formatting helpers ---------------------------------------------------


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = "\n".join("| " + " | ".join(row) + " |" for row in rows)
    return f"{head}\n{sep}\n{body}"


def _fmt_num(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v:.2f}"


def _fmt_pct_decimal(v: float | None) -> str:
    """Format a decimal (0.20) as '20.0'."""
    if v is None:
        return "n/a"
    return f"{v * 100:.1f}"


def _fmt_signed_pct(v: float | None) -> str:
    """Already a percent number; just format with sign."""
    if v is None:
        return "n/a"
    return f"{v:+.1f}"


def _fmt_money(v: float | None) -> str:
    if v is None:
        return "n/a"
    av = abs(v)
    if av >= 1e12:
        return f"${v/1e12:.1f}T"
    if av >= 1e9:
        return f"${v/1e9:.0f}B"
    if av >= 1e6:
        return f"${v/1e6:.0f}M"
    return f"${v:,.2f}"


def _parse_money(s: str) -> float | None:
    s = s.strip().lstrip("$").replace(",", "")
    if not s or s.lower() == "n/a":
        return None
    mult = 1.0
    if s.endswith(("T",)):
        mult, s = 1e12, s[:-1]
    elif s.endswith(("B",)):
        mult, s = 1e9, s[:-1]
    elif s.endswith(("M",)):
        mult, s = 1e6, s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None
