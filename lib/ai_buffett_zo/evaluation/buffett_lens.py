"""Buffett-lens query bundles over indexed SEC filings.

For each lens dimension (moat, management, financials, risks) we have a
canonical query + section filter. `view()` runs each dimension as a
secrag.search and returns top-k hits per dimension, ready for skill scripts
to render or compose into a thesis.

The lens is reused across Phase B skills:
- clarion-single-stock-eval: render the snippets, let the chat reason
- clarion-thesis-write: pull snippets to seed thesis sections
- clarion-thesis-monitor: re-run periodically to detect drift
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_buffett_zo.secrag import SearchHit, search


@dataclass(frozen=True)
class LensSpec:
    """Dimension spec: title, query phrase, section filter, top-k."""

    title: str
    query: str
    sections: tuple[str, ...]
    top_k: int


# Four dimensions, ordered for evaluation: moat first (durability test),
# then management (alignment), then financials (numbers tell the truth),
# then risks (what could break the thesis).
LENS_DIMENSIONS: dict[str, LensSpec] = {
    "moat": LensSpec(
        title="Moat & competitive position",
        query=(
            "competitive advantage moat barriers to entry pricing power "
            "switching costs network effect brand scale"
        ),
        sections=("business", "mdna"),
        top_k=4,
    ),
    "management": LensSpec(
        title="Management & capital allocation",
        query=(
            "executive officers compensation capital allocation buyback "
            "dividend strategy share repurchase"
        ),
        sections=("business", "mdna"),
        top_k=3,
    ),
    "financials": LensSpec(
        title="Financial trends",
        query=(
            "revenue growth operating margin gross margin free cash flow "
            "capital expenditure debt leverage"
        ),
        sections=("mdna", "financial_statements"),
        top_k=4,
    ),
    "risks": LensSpec(
        title="Risk factors",
        query=(
            "risk regulation supply chain competition customer concentration "
            "litigation cybersecurity"
        ),
        sections=("risk_factors",),
        top_k=5,
    ),
}


@dataclass(frozen=True)
class LensView:
    """One dimension's search result, with the original hits attached."""

    dimension: str
    title: str
    hits: list[SearchHit]


def view(
    ticker: str,
    *,
    sec_root: Path,
    dimensions: list[str] | None = None,
) -> list[LensView]:
    """Run all (or specified) Buffett-lens dimensions for `ticker`.

    Each dimension produces a LensView whose `hits` may be empty if the
    corpus has nothing matching the query. The list always includes one
    LensView per requested dimension — callers can render "no hits" cleanly.
    """
    dims = dimensions or list(LENS_DIMENSIONS.keys())
    out: list[LensView] = []
    for d in dims:
        if d not in LENS_DIMENSIONS:
            raise ValueError(f"unknown lens dimension: {d}")
        spec = LENS_DIMENSIONS[d]
        hits = search(
            spec.query,
            root=sec_root,
            tickers=[ticker.upper()],
            section_labels=list(spec.sections),
            top_k=spec.top_k,
        )
        out.append(LensView(dimension=d, title=spec.title, hits=hits))
    return out
