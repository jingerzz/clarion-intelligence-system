"""Stage 1 scoring + regime-adjusted thresholds + sector cap.

Source of truth: docs/ALLOCATION-POLICY.md and the AWB value-screener
framework (8-factor composite, 30% on valuation, sector cap of 3 per GICS
in the top 10 with a relaxation when fewer than 4 sectors are represented).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ai_buffett_zo.screener.types import (
    Candidate,
    ScoredCandidate,
    SectorCapResult,
)

# ---- Regime-adjusted threshold filters ------------------------------------


@dataclass(frozen=True)
class Thresholds:
    """Binary cutoffs applied before scoring. Candidates failing all of them
    are excluded from the ranked list (they don't meet the bar at any size)."""

    pe_max: float
    pfcf_max: float
    de_max: float
    roe_min_pct: float       # whole-percent min, e.g. 12.0 = 12%
    op_margin_min_pct: float


# Per AWB value-screener Step 1.1 table.
THRESHOLDS_BY_REGIME: dict[str, Thresholds] = {
    "green":  Thresholds(pe_max=25, pfcf_max=20, de_max=1.0, roe_min_pct=12, op_margin_min_pct=10),
    "blue":   Thresholds(pe_max=25, pfcf_max=20, de_max=1.0, roe_min_pct=12, op_margin_min_pct=10),
    "orange": Thresholds(pe_max=20, pfcf_max=16, de_max=0.8, roe_min_pct=15, op_margin_min_pct=12),
    "red":    Thresholds(pe_max=15, pfcf_max=12, de_max=0.5, roe_min_pct=18, op_margin_min_pct=15),
    "danger": Thresholds(pe_max=15, pfcf_max=12, de_max=0.5, roe_min_pct=18, op_margin_min_pct=15),
}


def thresholds_for(regime_color: str) -> Thresholds:
    return THRESHOLDS_BY_REGIME.get(regime_color.lower(), THRESHOLDS_BY_REGIME["orange"])


def passes_thresholds(candidate: Candidate, t: Thresholds) -> bool:
    """Apply the binary regime-adjusted filter. Missing data passes (counted
    as 'unknown' rather than 'fail') — this avoids excluding strong candidates
    just because the screener site didn't return one metric."""
    checks = (
        candidate.pe is None or candidate.pe <= t.pe_max,
        candidate.pfcf is None or candidate.pfcf <= t.pfcf_max,
        candidate.de is None or candidate.de <= t.de_max,
        candidate.roe is None or candidate.roe * 100 >= t.roe_min_pct,
        candidate.op_margin is None or candidate.op_margin * 100 >= t.op_margin_min_pct,
    )
    return all(checks)


# ---- Composite score formula -----------------------------------------------


# Weights per AWB value-screener Step 1.3. Sum to 100.
_FORMULA_WEIGHTS: dict[str, float] = {
    "pe": 15.0,
    "pfcf": 15.0,
    "roe": 15.0,
    "roic": 10.0,
    "op_margin": 10.0,
    "de": 15.0,
    "profit_margin": 10.0,
    "insider": 10.0,
}


def _score_pe(pe: float | None) -> float | None:
    """Lower P/E is better. P/E of 25 → 0; P/E of 0 → 100. Clamp [0, 100]."""
    if pe is None:
        return None
    return max(0.0, min(100.0, (25 - pe) / 25 * 100))


def _score_pfcf(pfcf: float | None) -> float | None:
    if pfcf is None:
        return None
    return max(0.0, min(100.0, (20 - pfcf) / 20 * 100))


def _score_roe(roe: float | None) -> float | None:
    """ROE is decimal (0.20 = 20%). 40% → 100; 0% → 0."""
    if roe is None:
        return None
    return max(0.0, min(100.0, roe * 100 / 40 * 100))


def _score_roic(roic: float | None) -> float | None:
    if roic is None:
        return None
    return max(0.0, min(100.0, roic * 100 / 30 * 100))


def _score_op_margin(op_margin: float | None) -> float | None:
    if op_margin is None:
        return None
    return max(0.0, min(100.0, op_margin * 100 / 40 * 100))


def _score_de(de: float | None) -> float | None:
    """D/E of 0 → 100; D/E of 1.0 → 0."""
    if de is None:
        return None
    return max(0.0, min(100.0, (1 - de) * 100))


def _score_profit_margin(margin: float | None) -> float | None:
    if margin is None:
        return None
    return max(0.0, min(100.0, margin * 100 / 30 * 100))


def _score_insider(insider_pct: float | None) -> float | None:
    """Signed % of insider net buying. Bands per AWB Step 1.3.

    Order matters: the ±1% neutral band must claim its territory before the
    "any positive = net buying" or "any negative = net selling" buckets.
    """
    if insider_pct is None:
        return None
    if abs(insider_pct) <= 1:
        return 50.0  # neutral
    if insider_pct >= 5:
        return 90.0  # cluster buying
    if insider_pct > 0:
        return 75.0  # net buying
    if insider_pct < -10:
        return 15.0  # heavy selling
    return 30.0  # net selling


def composite_score(candidate: Candidate) -> ScoredCandidate:
    """Compute the 8-factor composite for one candidate.

    `contributing_weight` reports what fraction of the 100% weight was actually
    backed by data — useful for flagging candidates whose score is based on
    only a few of the eight factors.
    """
    parts: dict[str, float | None] = {
        "pe": _score_pe(candidate.pe),
        "pfcf": _score_pfcf(candidate.pfcf),
        "roe": _score_roe(candidate.roe),
        "roic": _score_roic(candidate.roic),
        "op_margin": _score_op_margin(candidate.op_margin),
        "de": _score_de(candidate.de),
        "profit_margin": _score_profit_margin(candidate.profit_margin),
        "insider": _score_insider(candidate.insider_pct),
    }
    contributing = 0.0
    weighted_sum = 0.0
    component_scores: dict[str, float] = {}
    for key, score in parts.items():
        if score is None:
            continue
        w = _FORMULA_WEIGHTS[key]
        contributing += w
        weighted_sum += score * w
        component_scores[key] = score

    composite = (weighted_sum / contributing) if contributing > 0 else 0.0
    return ScoredCandidate(
        candidate=candidate,
        composite=round(composite, 1),
        component_scores={k: round(v, 1) for k, v in component_scores.items()},
        contributing_weight=round(contributing, 1),
    )


def score_and_rank(
    candidates: Iterable[Candidate],
    *,
    regime_color: str,
) -> list[ScoredCandidate]:
    """Apply regime thresholds, score, and rank by composite descending."""
    thresh = thresholds_for(regime_color)
    out: list[ScoredCandidate] = []
    for c in candidates:
        sc = composite_score(c)
        passed = passes_thresholds(c, thresh)
        out.append(
            ScoredCandidate(
                candidate=sc.candidate,
                composite=sc.composite,
                component_scores=sc.component_scores,
                contributing_weight=sc.contributing_weight,
                passed_threshold=passed,
            )
        )
    out.sort(key=lambda s: (-s.composite, s.candidate.ticker))
    return out


# ---- Sector cap ------------------------------------------------------------


def apply_sector_cap(
    ranked: list[ScoredCandidate],
    *,
    target_size: int = 10,
    cap_per_sector: int = 3,
    relax_threshold_sectors: int = 4,
) -> SectorCapResult:
    """Pick the top `target_size` from `ranked`, capping per-sector representation.

    The relaxation rule (per AWB Step 1.4): if fewer than `relax_threshold_sectors`
    distinct sectors are represented in the top 2*target_size by raw score, the
    cap is relaxed to `cap_per_sector + 1` to acknowledge a genuinely-concentrated
    universe.

    Returns (top_after_cap, displaced_with_reasons, sectors_relaxed).
    """
    if not ranked:
        return SectorCapResult(top=[], displaced=[], sectors_relaxed=False)

    # Inspect the top 2*target_size to decide whether to relax
    inspect_window = ranked[: target_size * 2]
    distinct_sectors = {s.candidate.sector for s in inspect_window if s.passed_threshold}
    relaxed = len(distinct_sectors) < relax_threshold_sectors
    effective_cap = cap_per_sector + 1 if relaxed else cap_per_sector

    sector_counts: dict[str, int] = {}
    top: list[ScoredCandidate] = []
    displaced: list[tuple[ScoredCandidate, str]] = []
    for s in ranked:
        if not s.passed_threshold:
            displaced.append((s, "failed regime threshold filter"))
            continue
        sec = s.candidate.sector
        if sector_counts.get(sec, 0) >= effective_cap:
            displaced.append(
                (s, f"sector cap: {sec} already has {effective_cap} representatives")
            )
            continue
        top.append(s)
        sector_counts[sec] = sector_counts.get(sec, 0) + 1
        if len(top) >= target_size:
            break

    return SectorCapResult(top=top, displaced=displaced, sectors_relaxed=relaxed)
