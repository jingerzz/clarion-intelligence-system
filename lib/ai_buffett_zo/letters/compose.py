"""Render quarterly + finalization sections from system data.

Tables that the system can fill deterministically (regime, thesis health) are
populated. Narrative sections (What We Did, What We Learned, Year in Context,
Mistakes & Lessons, Looking Ahead) are scaffolded with [TODO] markers — the
human writes them with chat assistance. This is the design philosophy from
LIVING-LETTER-FORMAT.md: the system supplies data, the human supplies thinking.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from ai_buffett_zo.regime import RegimeSnapshot
from ai_buffett_zo.theses import Bucket, ThesisMetadata


def render_quarterly_section(
    *,
    quarter: int,
    update_date: date,
    regime: RegimeSnapshot | None,
    active_theses: Iterable[ThesisMetadata],
) -> str:
    """Render the body of one quarter's section (without the `## Q{N}:` header).

    Auto-fills:
    - Update date
    - Regime (if available)
    - Thesis Health table (from active theses)
    - Portfolio Snapshot bucket positions (tickers per bucket from active theses)

    Marks as [TODO]:
    - Macro events
    - Portfolio actuals (we don't track positions outside theses in v1)
    - What We Did, What We Learned
    - Performance numbers
    """
    theses = list(active_theses)
    parts: list[str] = []
    parts.append(f"**Updated: {update_date.isoformat()}**")
    parts.append("")

    parts.extend(_render_regime_section(regime))
    parts.append("")

    parts.extend(_render_portfolio_snapshot(theses))
    parts.append("")

    parts.extend([
        "### What We Did",
        "",
        "[TODO Narrative of key decisions. New positions, closes, thesis changes. "
        "Be specific: \"Added 50 shares of X at $Y because Z\" — not "
        "\"increased equity exposure.\" Include the reasoning at the time, "
        "not sanitized with hindsight.]",
        "",
    ])

    parts.extend(_render_thesis_health(theses))
    parts.append("")

    parts.extend([
        "### What We Learned",
        "",
        "[TODO The most valuable section. What surprised us? What did we get wrong? "
        "What pattern did we notice? What would we do differently? Be honest — "
        "this is the section that compounds in value over years.]",
        "",
    ])

    parts.extend([
        "### Performance",
        f"- Portfolio return (Q{quarter}): [TODO]",
        f"- S&P 500 (Q{quarter}): [TODO]",
        f"- 60/40 benchmark (Q{quarter}): [TODO]",
        "- YTD: [TODO]",
    ])
    return "\n".join(parts)


def render_finalization(
    *,
    year: int,
    finalize_date: date,
    active_theses: Iterable[ThesisMetadata],
) -> tuple[str, str]:
    """Year-end finalization: returns (year_in_context_body, full_year_summary_body)."""
    theses = list(active_theses)
    year_in_context = (
        "[TODO 2-3 paragraphs setting the scene. What was the macro environment? "
        "What regime(s) did the system operate in? What was the dominant narrative — "
        "and did the system agree with it? Written in hindsight with the benefit of "
        "the full year's perspective.]"
    )

    summary_parts: list[str] = []
    summary_parts.append(f"*Finalized: {finalize_date.isoformat()}*")
    summary_parts.append(f"*This letter covers the period {year}-01-01 to {year}-12-31.*")
    summary_parts.append("")

    summary_parts.append("### Performance")
    summary_parts.append("")
    summary_parts.append(
        "| Metric | Portfolio | S&P 500 | 60/40 | Risk-Free |\n"
        "|---|---|---|---|---|\n"
        "| Total Return | [TODO] | [TODO] | [TODO] | [TODO] |\n"
        "| Max Drawdown | [TODO] | [TODO] | [TODO] | [TODO] |\n"
        "| Sharpe Ratio | [TODO] | [TODO] | [TODO] | [TODO] |\n"
        "| Best Month | [TODO] | [TODO] | [TODO] | [TODO] |\n"
        "| Worst Month | [TODO] | [TODO] | [TODO] | [TODO] |"
    )
    summary_parts.append("")

    summary_parts.append("### By Bucket")
    summary_parts.append("")
    summary_parts.append(
        "| Bucket | Return | Contribution | Key Winner | Key Loser |\n"
        "|---|---|---|---|---|\n"
        "| Value | [TODO] | [TODO] | [TODO] | [TODO] |\n"
        "| Systematic | [TODO] | [TODO] | [TODO] | [TODO] |\n"
        "| Short | [TODO] | [TODO] | [TODO] | [TODO] |\n"
        "| YOLO | [TODO] | [TODO] | [TODO] | [TODO] |"
    )
    summary_parts.append("")

    summary_parts.append("### Mistakes & Lessons")
    summary_parts.append("")
    summary_parts.append(
        "[TODO The year's most important mistakes, ranked by impact. For each:\n"
        "- What happened\n"
        "- What we thought at the time\n"
        "- What we should have seen\n"
        "- The lesson going forward]"
    )
    summary_parts.append("")

    summary_parts.append("### Theses: Final Scorecard")
    summary_parts.append("")
    if theses:
        rows = ["| Ticker | Bucket | Status | Final Score | Outcome |", "|---|---|---|---|---|"]
        for t in sorted(theses, key=lambda m: m.ticker):
            score = str(t.health_score) if t.health_score is not None else "—"
            rows.append(f"| {t.ticker} | {t.bucket} | {t.status} | {score} | [TODO] |")
        summary_parts.extend(rows)
    else:
        summary_parts.append("[TODO No theses to score. List every thesis active during the year.]")
    summary_parts.append("")

    summary_parts.append("### Looking Ahead")
    summary_parts.append("")
    summary_parts.append(
        "[TODO Not predictions. Observations about the current environment, "
        "the opportunity set, and what the system is watching. What regimes "
        "might we be entering? Where is the risk? Where is the asymmetry?]"
    )

    return year_in_context, "\n".join(summary_parts)


# ---- Helpers --------------------------------------------------------------


def _render_regime_section(regime: RegimeSnapshot | None) -> list[str]:
    out = ["### Regime & Environment"]
    if regime is None:
        out.append("- SPY/TLT regime: [TODO — clarion-regime-check unavailable when this section was written]")
    else:
        out.append(
            f"- SPY/TLT regime at update: **{regime.color.upper()}** "
            f"(as of {regime.asof.isoformat()})"
        )
        out.append(f"- Rationale: {regime.rationale}")
    out.append("- S&P 500 P/E at quarter start: [TODO from clarion-expected-return-calc]")
    out.append("- Key macro events: [TODO Fed decisions, earnings season themes, geopolitical]")
    return out


def _render_portfolio_snapshot(theses: list[ThesisMetadata]) -> list[str]:
    """Render the portfolio bucket table.

    v1 fills "Key Positions" with tickers from active theses grouped by bucket.
    Target/Actual columns are TODO — CIS doesn't track real-time portfolio
    weights outside thesis cost_basis × shares (and even those are user-set).
    """
    by_bucket: dict[Bucket, list[str]] = {"value": [], "systematic": [], "short": [], "yolo": []}
    for t in theses:
        if t.bucket in by_bucket:
            by_bucket[t.bucket].append(t.ticker)

    out = [
        "### Portfolio Snapshot",
        "",
        "*Target weights from `docs/ALLOCATION-POLICY.md`. Actual weights and key "
        "positions per bucket — auto-populated from active theses; positions outside "
        "the thesis archive must be filled manually.*",
        "",
        "| Bucket | Target | Actual | Key Positions |",
        "|---|---|---|---|",
    ]
    for label, target_pct in (
        ("Value", "50%"),
        ("Systematic", "30%"),
        ("Short", "10%"),
        ("YOLO", "10%"),
    ):
        bucket: Bucket = label.lower()  # type: ignore[assignment]
        positions = ", ".join(by_bucket[bucket]) if by_bucket[bucket] else "[TODO]"
        out.append(f"| {label} ({target_pct}) | {target_pct} | [TODO] | {positions} |")
    return out


def _render_thesis_health(theses: list[ThesisMetadata]) -> list[str]:
    out = ["### Thesis Health"]
    if not theses:
        out.append("")
        out.append("[No active theses at this update.]")
        return out
    out.append("")
    out.append("| Position | Bucket | Score | Status | Notes |")
    out.append("|---|---|---|---|---|")
    for t in sorted(theses, key=lambda m: m.ticker):
        score = str(t.health_score) if t.health_score is not None else "—"
        out.append(f"| {t.ticker} | {t.bucket} | {score} | {t.status} | [TODO key dev] |")
    return out
