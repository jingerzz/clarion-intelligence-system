"""Tests for ai_buffett_zo.screener.watchlist_io."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ai_buffett_zo.screener import (
    Candidate,
    ScoredCandidate,
    ScreenContext,
    SectorCapResult,
    latest_watchlist,
    list_watchlists,
    parse_ranked_table,
    render_watchlist,
    watchlist_path,
)


def _c(
    ticker: str,
    sector: str = "Tech",
    *,
    pe: float = 15.0,
    pfcf: float = 12.0,
    roe: float = 0.20,
    de: float = 0.4,
    op_margin: float = 0.25,
    profit_margin: float = 0.18,
    insider_pct: float = 0.0,
    price: float = 150.0,
    market_cap: float = 100e9,
) -> Candidate:
    return Candidate(
        ticker=ticker,
        company=f"{ticker} Inc.",
        sector=sector,
        pe=pe,
        pfcf=pfcf,
        roe=roe,
        roic=0.18,
        op_margin=op_margin,
        profit_margin=profit_margin,
        de=de,
        insider_pct=insider_pct,
        market_cap=market_cap,
        price=price,
    )


def _scored(c: Candidate, score: float) -> ScoredCandidate:
    return ScoredCandidate(candidate=c, composite=score, passed_threshold=True)


def _ctx(d: date = date(2026, 5, 7)) -> ScreenContext:
    return ScreenContext(
        screen_date=d,
        regime_color="orange",
        rf_rate_pct=4.45,
        hurdle_rate_pct=10.45,
        sp500_cape=35.2,
        sp500_trailing_pe=28.4,
        implied_return_low_pct=0.0,
        implied_return_high_pct=3.0,
        notes="Mega-cap led rally; verify breadth before sizing.",
    )


# ---- render_watchlist ------------------------------------------------------


def test_render_watchlist_includes_all_canonical_sections() -> None:
    ranked = [_scored(_c("NVDA"), 75.0), _scored(_c("AAPL", "Tech"), 70.0)]
    cap = SectorCapResult(top=ranked[:1], displaced=[(ranked[1], "sector cap: Tech already has 1 representative")], sectors_relaxed=False)
    out = render_watchlist(context=_ctx(), ranked=ranked, cap_result=cap)
    for header in [
        "# S&P 500 Value Screen — 2026-05-07",
        "## Context",
        "## Stage 1 Ranked Results",
        "## Top",
        "After Sector Cap",
        "## Sniff Test",
        "## Passed On",
        "## Existing Theses Impact",
    ]:
        assert header in out


def test_render_context_has_regime_and_hurdle() -> None:
    out = render_watchlist(
        context=_ctx(),
        ranked=[_scored(_c("X"), 50.0)],
        cap_result=SectorCapResult(top=[_scored(_c("X"), 50.0)], displaced=[]),
    )
    assert "ORANGE" in out
    assert "Hurdle Rate" in out
    assert "10.45%" in out
    assert "**Tightened**" in out  # orange stance


def test_render_context_handles_danger_state() -> None:
    ctx = ScreenContext(
        screen_date=date(2026, 5, 7),
        regime_color="danger",
        danger_state=True,
        rf_rate_pct=4.45,
    )
    out = render_watchlist(
        context=ctx,
        ranked=[_scored(_c("X"), 50.0)],
        cap_result=SectorCapResult(top=[], displaced=[]),
    )
    assert "DANGER" in out
    assert "**Maximum Value Only**" in out


def test_render_ranked_table_marks_top_score_bold() -> None:
    ranked = [_scored(_c("FIRST"), 90.5), _scored(_c("SECOND"), 80.0)]
    out = render_watchlist(
        context=_ctx(),
        ranked=ranked,
        cap_result=SectorCapResult(top=ranked, displaced=[]),
    )
    assert "**90.5**" in out


def test_render_includes_sector_cap_relaxation_note() -> None:
    cap = SectorCapResult(
        top=[_scored(_c("X"), 50.0)], displaced=[], sectors_relaxed=True
    )
    out = render_watchlist(context=_ctx(), ranked=[_scored(_c("X"), 50.0)], cap_result=cap)
    assert "Sector cap relaxed" in out


def test_render_includes_what_changed_when_provided() -> None:
    out = render_watchlist(
        context=_ctx(),
        ranked=[_scored(_c("X"), 50.0)],
        cap_result=SectorCapResult(top=[_scored(_c("X"), 50.0)], displaced=[]),
        notes_what_changed="Market rallied 10% in 20 days.",
    )
    assert "## What Changed Since Last Screen" in out
    assert "Market rallied 10%" in out


def test_render_omits_what_changed_when_empty() -> None:
    out = render_watchlist(
        context=_ctx(),
        ranked=[_scored(_c("X"), 50.0)],
        cap_result=SectorCapResult(top=[_scored(_c("X"), 50.0)], displaced=[]),
    )
    assert "What Changed Since Last Screen" not in out


def test_render_includes_displaced_sector_notes() -> None:
    ranked = [
        _scored(_c("FIN1", "FinSvcs"), 90.0),
        _scored(_c("FIN2", "FinSvcs"), 80.0),
        _scored(_c("FIN3", "FinSvcs"), 70.0),
        _scored(_c("FIN4", "FinSvcs"), 60.0),
    ]
    cap = SectorCapResult(
        top=ranked[:3],
        displaced=[(ranked[3], "sector cap: FinSvcs already has 3 representatives")],
        sectors_relaxed=False,
    )
    out = render_watchlist(context=_ctx(), ranked=ranked, cap_result=cap)
    assert "Displaced by sector cap" in out
    assert "FIN4" in out


# ---- parse_ranked_table ----------------------------------------------------


def test_parse_ranked_table_round_trip() -> None:
    ranked = [
        _scored(_c("NVDA", "Tech", price=140.50), 75.5),
        _scored(_c("AAPL", "Tech", price=215.00), 65.0),
    ]
    cap = SectorCapResult(top=ranked, displaced=[])
    rendered = render_watchlist(context=_ctx(), ranked=ranked, cap_result=cap)
    rows = parse_ranked_table(rendered)
    assert len(rows) == 2
    assert rows[0].rank == 1
    assert rows[0].ticker == "NVDA"
    assert rows[0].score == 75.5
    assert rows[0].sector == "Tech"
    assert rows[0].price == 140.50


def test_parse_ranked_table_empty_when_no_section() -> None:
    assert parse_ranked_table("# No screen\n") == []


# ---- list_watchlists / latest_watchlist / watchlist_path -------------------


def test_watchlist_path_format() -> None:
    p = watchlist_path(Path("/tmp"), date(2026, 5, 7))
    assert p.name == "sp500-screen-2026-05-07.md"


def test_list_and_latest_watchlists(tmp_path: Path) -> None:
    files = [
        tmp_path / "sp500-screen-2026-04-11.md",
        tmp_path / "sp500-screen-2026-04-30.md",
        tmp_path / "sp500-screen-2026-05-07.md",
        tmp_path / "notes.txt",  # not a watchlist
    ]
    for f in files[:3]:
        f.write_text("placeholder")
    files[3].write_text("not a screen")

    listed = list_watchlists(tmp_path)
    assert len(listed) == 3
    assert listed[-1].name.endswith("2026-05-07.md")
    assert latest_watchlist(tmp_path) == files[2]


def test_list_watchlists_empty_when_root_missing(tmp_path: Path) -> None:
    assert list_watchlists(tmp_path / "nope") == []
    assert latest_watchlist(tmp_path / "nope") is None
