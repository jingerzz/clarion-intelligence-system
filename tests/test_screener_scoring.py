"""Tests for ai_buffett_zo.screener.scoring."""

from __future__ import annotations


from ai_buffett_zo.screener import (
    Candidate,
    ScoredCandidate,
    apply_sector_cap,
    composite_score,
    passes_thresholds,
    score_and_rank,
    thresholds_for,
)


def _c(
    ticker: str,
    *,
    sector: str = "Tech",
    pe: float | None = 12.0,
    pfcf: float | None = 10.0,
    roe: float | None = 0.20,
    roic: float | None = 0.18,
    op_margin: float | None = 0.30,
    profit_margin: float | None = 0.20,
    de: float | None = 0.30,
    insider_pct: float | None = 0.0,
    market_cap: float | None = 100e9,
    price: float | None = 100.0,
    company: str | None = None,
) -> Candidate:
    return Candidate(
        ticker=ticker,
        company=company or f"{ticker} Inc.",
        sector=sector,
        pe=pe,
        pfcf=pfcf,
        roe=roe,
        roic=roic,
        op_margin=op_margin,
        profit_margin=profit_margin,
        de=de,
        insider_pct=insider_pct,
        market_cap=market_cap,
        price=price,
    )


# ---- thresholds_for ---------------------------------------------------------


def test_thresholds_tighten_with_regime() -> None:
    g = thresholds_for("green")
    o = thresholds_for("orange")
    r = thresholds_for("red")
    assert g.pe_max > o.pe_max > r.pe_max
    assert g.roe_min_pct < o.roe_min_pct < r.roe_min_pct
    assert g.de_max > o.de_max > r.de_max


def test_thresholds_unknown_regime_defaults_orange() -> None:
    assert thresholds_for("turquoise") == thresholds_for("orange")


# ---- passes_thresholds -----------------------------------------------------


def test_passes_thresholds_orange_typical() -> None:
    t = thresholds_for("orange")
    c = _c("X", pe=18.0, pfcf=14.0, de=0.5, roe=0.20, op_margin=0.15)
    assert passes_thresholds(c, t) is True


def test_passes_thresholds_fails_on_pe() -> None:
    t = thresholds_for("orange")
    c = _c("X", pe=22.0)  # > 20 in orange
    assert passes_thresholds(c, t) is False


def test_passes_thresholds_fails_on_roe() -> None:
    t = thresholds_for("orange")
    c = _c("X", roe=0.10)  # 10% < 15% in orange
    assert passes_thresholds(c, t) is False


def test_passes_thresholds_missing_data_passes() -> None:
    """A candidate with one None field shouldn't fail just because the data is missing."""
    t = thresholds_for("orange")
    c = _c("X", pe=None)  # missing
    assert passes_thresholds(c, t) is True


# ---- composite_score -------------------------------------------------------


def test_composite_full_data_returns_score_in_0_100() -> None:
    s = composite_score(_c("X"))
    assert 0 <= s.composite <= 100
    assert s.contributing_weight == 100.0
    assert len(s.component_scores) == 8


def test_composite_low_pe_scores_higher_than_high_pe() -> None:
    cheap = composite_score(_c("CHEAP", pe=5.0))
    pricy = composite_score(_c("PRICY", pe=22.0))
    assert cheap.composite > pricy.composite


def test_composite_high_roe_scores_higher_than_low_roe() -> None:
    great = composite_score(_c("GREAT", roe=0.40))
    bad = composite_score(_c("BAD", roe=0.05))
    assert great.composite > bad.composite


def test_composite_missing_field_reduces_contributing_weight() -> None:
    s = composite_score(_c("X", pe=None, pfcf=None))
    assert s.contributing_weight == 100.0 - 15.0 - 15.0  # missing pe + pfcf
    assert "pe" not in s.component_scores
    assert "pfcf" not in s.component_scores


def test_composite_insider_buying_scores_high() -> None:
    s = composite_score(_c("X", insider_pct=8.0))
    assert s.component_scores["insider"] == 90.0


def test_composite_neutral_insider_scores_50() -> None:
    s = composite_score(_c("X", insider_pct=0.5))
    assert s.component_scores["insider"] == 50.0


def test_composite_heavy_insider_selling_scores_low() -> None:
    s = composite_score(_c("X", insider_pct=-15.0))
    assert s.component_scores["insider"] == 15.0


def test_composite_zero_data_returns_zero() -> None:
    c = Candidate(ticker="X", sector="Tech")  # all None
    s = composite_score(c)
    assert s.composite == 0.0
    assert s.contributing_weight == 0.0


# ---- score_and_rank --------------------------------------------------------


def test_score_and_rank_orders_descending_and_marks_threshold_failures() -> None:
    candidates = [
        _c("HIGH", pe=8.0, roe=0.30),
        _c("LOW", pe=20.0, roe=0.18),
        _c("FAIL", pe=22.0),  # fails orange threshold
    ]
    ranked = score_and_rank(candidates, regime_color="orange")
    tickers = [s.candidate.ticker for s in ranked]
    # HIGH and LOW pass; FAIL also passes the formula but gets passed=False
    assert tickers[0] == "HIGH"
    fail = next(s for s in ranked if s.candidate.ticker == "FAIL")
    assert fail.passed_threshold is False


def test_score_and_rank_ties_broken_by_ticker() -> None:
    """Identical candidates should sort by ticker for determinism."""
    same_a = _c("AAA")
    same_b = _c("BBB")
    ranked = score_and_rank([same_b, same_a], regime_color="orange")
    assert [s.candidate.ticker for s in ranked] == ["AAA", "BBB"]


# ---- apply_sector_cap ------------------------------------------------------


def _scored(ticker: str, sector: str, score: float, *, passed: bool = True) -> ScoredCandidate:
    return ScoredCandidate(
        candidate=_c(ticker, sector=sector),
        composite=score,
        passed_threshold=passed,
    )


def test_sector_cap_keeps_top_3_per_sector() -> None:
    ranked = [
        _scored("FIN1", "FinSvcs", 90),
        _scored("FIN2", "FinSvcs", 80),
        _scored("FIN3", "FinSvcs", 70),
        _scored("FIN4", "FinSvcs", 60),  # should be displaced
        _scored("TEC1", "Tech", 55),
        _scored("HC1", "HC", 50),
        _scored("INDUS1", "Indust", 45),
    ]
    result = apply_sector_cap(ranked, target_size=10, cap_per_sector=3)
    tickers = [s.candidate.ticker for s in result.top]
    assert "FIN4" not in tickers
    assert {"FIN1", "FIN2", "FIN3"}.issubset(set(tickers))
    displaced_tickers = [s.candidate.ticker for s, _ in result.displaced]
    assert "FIN4" in displaced_tickers


def test_sector_cap_relaxes_when_few_distinct_sectors() -> None:
    """Fewer than 4 sectors in top-20 → cap relaxes to 4 per sector."""
    ranked = [
        _scored(f"FIN{i}", "FinSvcs", 100 - i) for i in range(6)
    ] + [
        _scored(f"TEC{i}", "Tech", 80 - i) for i in range(4)
    ]
    result = apply_sector_cap(ranked, target_size=10, cap_per_sector=3)
    assert result.sectors_relaxed is True
    fin_count = sum(1 for s in result.top if s.candidate.sector == "FinSvcs")
    assert fin_count == 4  # cap was 3, relaxed to 4


def test_sector_cap_skips_threshold_failures() -> None:
    ranked = [
        _scored("FAIL", "FinSvcs", 99, passed=False),
        _scored("PASS", "FinSvcs", 50, passed=True),
    ]
    result = apply_sector_cap(ranked, target_size=10, cap_per_sector=3)
    tickers = [s.candidate.ticker for s in result.top]
    assert tickers == ["PASS"]
    displaced_tickers = [s.candidate.ticker for s, _ in result.displaced]
    assert "FAIL" in displaced_tickers


def test_sector_cap_target_size_caps_total() -> None:
    ranked = [_scored(f"T{i}", f"Sec{i % 6}", 100 - i) for i in range(20)]
    result = apply_sector_cap(ranked, target_size=10, cap_per_sector=3)
    assert len(result.top) == 10


def test_sector_cap_empty_input() -> None:
    result = apply_sector_cap([], target_size=10)
    assert result.top == []
    assert result.displaced == []
    assert result.sectors_relaxed is False
