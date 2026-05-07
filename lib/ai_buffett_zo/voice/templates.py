"""Output formatting helpers — Clarion Intelligence System voice.

All skill scripts that emit prose to chat should use these helpers so output
style stays consistent across regime / SEC / single-stock / screener / thesis
/ letter contexts.

Voice principles (from AI Warren Buffett DESIGN-LANGUAGE.md):
- Show the math always.
- Never fabricate data. Cite the source (filing, ticker:date, regime signal).
- Tier 1 (filings, regime, market data) > Tier 2 (verified external) > Tier 3
  (estimates, sentiment).
- Conservative and neutral; surface uncertainty, don't paper over it.

These helpers are intentionally small. They format markdown — they do NOT
fabricate data, round/format numbers (caller controls precision), or
choose what to say (caller chooses).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

SIGNATURE = "Clarion Intelligence System"


def header(title: str, subtitle: str | None = None) -> str:
    """Top of an analysis output. e.g. 'Market Regime — 2026-05-06'."""
    line = f"## {title}"
    if subtitle:
        line += f"\n_{subtitle}_"
    return line


def footer(
    *,
    source_lines: Sequence[str] | None = None,
    model: str | None = None,
) -> str:
    """Tool stamp at the bottom. UTC timestamp; UI can localize.

    source_lines: free-form citation lines (use cite_filing / cite_quote helpers).
    model: the Zo model_name actually used, if relevant.
    """
    parts = [f"*{SIGNATURE} · {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}*"]
    if source_lines:
        parts.append("\n**Sources**")
        parts.extend(f"- {s}" for s in source_lines)
    if model:
        parts.append(f"\n_Model: `{model}`_")
    return "\n".join(parts)


def md_table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    """Plain markdown table. Caller controls cell content (formatting, precision)."""
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = "\n".join("| " + " | ".join(str(c) for c in row) + " |" for row in rows)
    return f"{head}\n{sep}\n{body}"


def cite_filing(ticker: str, form: str, filed: str, page: int | None = None) -> str:
    """Citation for a SEC filing. Use after any quote or figure pulled from filings."""
    base = f"{ticker} {form} filed {filed}"
    if page is not None:
        return f"{base} (p. {page})"
    return base


def cite_quote(ticker: str, asof: str) -> str:
    """Citation for a market data point. Always include the as-of timestamp."""
    return f"{ticker} as of {asof}"


def no_data(reason: str) -> str:
    """Standard response when a tier-1 source is unavailable.

    NEVER fabricate as fallback. The contract is: if we can't cite it, we don't say it.
    """
    return f"_Data unavailable: {reason}. No estimate substituted._"


def show_math(label: str, expression: str, value: object) -> str:
    """Inline math line.

    Example: show_math('Hurdle rate', '4.5% + 3.0%', '7.5%')
    -> '- **Hurdle rate**: 4.5% + 3.0% = **7.5%**'
    """
    return f"- **{label}**: {expression} = **{value}**"
