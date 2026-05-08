"""Tests for skills/clarion-thesis-write/scripts/write.py."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

from ai_buffett_zo.evaluation import Fundamentals
from ai_buffett_zo.theses import HEALTH_COMPONENT_NAMES, parse_thesis_metadata

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    REPO_ROOT / "skills" / "clarion-thesis-write" / "scripts" / "write.py"
)


@pytest.fixture(scope="module")
def write_mod():
    spec = importlib.util.spec_from_file_location("clarion_write", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["clarion_write"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    troot = tmp_path / "theses"
    sroot = tmp_path / "sec"
    monkeypatch.setenv("CLARION_THESES_ROOT", str(troot))
    monkeypatch.setenv("CLARION_SEC_ROOT", str(sroot))
    return troot, sroot


def _fake_fundamentals(ticker: str = "NVDA") -> Fundamentals:
    return Fundamentals(
        ticker=ticker,
        company=f"{ticker} Corporation",
        market_cap=3e12,
        trailing_pe=65.0,
        forward_pe=35.0,
        price_to_book=50.0,
        profit_margin=0.55,
        operating_margin=0.62,
        return_on_equity=1.20,
        return_on_assets=0.45,
        debt_to_equity=25.0,
        current_ratio=4.0,
        free_cash_flow=60e9,
        operating_cash_flow=65e9,
        dividend_yield=0.0003,
        week52_high=152.0,
        week52_low=80.0,
        last_close=140.50,
    )


def _args(
    ticker: str = "NVDA",
    *,
    bucket: str = "value",
    opened: date | None = None,
    force: bool = False,
    no_lens: bool = True,
    no_fundamentals: bool = True,
    require_indexed: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        ticker=ticker,
        bucket=bucket,
        opened=opened or date(2026, 5, 7),
        force=force,
        no_lens=no_lens,
        no_fundamentals=no_fundamentals,
        require_indexed=require_indexed,
    )


def _patch(write_mod, monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: skip lens + fundamentals (covered by no_lens/no_fundamentals flags)."""
    monkeypatch.setattr(write_mod, "fetch_fundamentals", lambda t: _fake_fundamentals(t))
    monkeypatch.setattr(write_mod, "lens_view", lambda ticker, sec_root: [])
    monkeypatch.setattr(write_mod, "list_indexed", lambda root, **kw: [])


# ---- run() basic happy path -------------------------------------------------


def test_run_creates_thesis_file(
    write_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(write_mod, monkeypatch)
    troot, _ = roots
    rc = write_mod.run(_args("NVDA"))
    assert rc == 0
    out = troot / "NVDA.md"
    assert out.exists()
    content = out.read_text()
    assert "# Thesis: NVDA" in content
    assert "## Metadata" in content
    assert "## Core Thesis" in content
    assert "## Kill Conditions" in content
    assert "## Health Scoring" in content
    assert "## History" in content


def test_run_metadata_parses(
    write_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(write_mod, monkeypatch)
    troot, _ = roots
    write_mod.run(_args("NVDA", bucket="yolo", opened=date(2024, 8, 1)))
    md = parse_thesis_metadata((troot / "NVDA.md").read_text())
    assert md is not None
    assert md.ticker == "NVDA"
    assert md.bucket == "yolo"
    assert md.opened == date(2024, 8, 1)
    assert md.status == "active"


def test_run_health_table_has_six_components(
    write_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(write_mod, monkeypatch)
    troot, _ = roots
    write_mod.run(_args("NVDA"))
    content = (troot / "NVDA.md").read_text()
    for name in HEALTH_COMPONENT_NAMES:
        assert name in content


def test_run_history_seeded_with_opened(
    write_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(write_mod, monkeypatch)
    troot, _ = roots
    write_mod.run(_args("NVDA", opened=date(2024, 8, 1)))
    content = (troot / "NVDA.md").read_text()
    assert "2024-08-01 | OPENED" in content


# ---- file existence / overwrite --------------------------------------------


def test_run_refuses_to_overwrite(
    write_mod,
    roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch(write_mod, monkeypatch)
    troot, _ = roots
    troot.mkdir(parents=True, exist_ok=True)
    (troot / "NVDA.md").write_text("# Existing")

    rc = write_mod.run(_args("NVDA"))
    assert rc == 1
    out = capsys.readouterr().out
    assert "THESIS_WRITE_ERROR" in out
    assert "already exists" in out
    assert (troot / "NVDA.md").read_text() == "# Existing"


def test_run_force_overwrites(
    write_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(write_mod, monkeypatch)
    troot, _ = roots
    troot.mkdir(parents=True, exist_ok=True)
    (troot / "NVDA.md").write_text("# Existing")

    rc = write_mod.run(_args("NVDA", force=True))
    assert rc == 0
    content = (troot / "NVDA.md").read_text()
    assert content != "# Existing"
    assert "# Thesis: NVDA" in content


# ---- fundamentals pre-population --------------------------------------------


def test_run_fundamentals_populate_current_price(
    write_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(write_mod, monkeypatch)
    troot, _ = roots
    write_mod.run(_args("NVDA", no_fundamentals=False))
    content = (troot / "NVDA.md").read_text()
    assert "$140.50" in content
    assert "NVDA Corporation" in content


def test_run_fundamentals_failure_is_non_fatal(
    write_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_t):
        raise RuntimeError("yfinance offline")

    monkeypatch.setattr(write_mod, "fetch_fundamentals", boom)
    monkeypatch.setattr(write_mod, "lens_view", lambda ticker, sec_root: [])
    monkeypatch.setattr(write_mod, "list_indexed", lambda root, **kw: [])

    troot, _ = roots
    rc = write_mod.run(_args("NVDA", no_fundamentals=False))
    assert rc == 0
    assert (troot / "NVDA.md").exists()


# ---- lens pre-population ----------------------------------------------------


def test_run_lens_populated_from_secrag(
    write_mod, roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """When indexed filings exist, lens hits are seeded into the evidence section."""
    troot, sroot = roots
    sroot.mkdir(parents=True, exist_ok=True)
    troot.mkdir(parents=True, exist_ok=True)

    # Pretend NVDA is indexed, with a single lens hit
    from ai_buffett_zo.evaluation import LensView
    from ai_buffett_zo.secrag import FilingMetadata, SearchHit

    fake_meta = FilingMetadata(
        cik="0000000000",
        ticker="NVDA",
        company="NVIDIA",
        form="10-K",
        filed=date(2026, 2, 21),
        period=date(2026, 1, 26),
        accession="acc-NVDA",
        primary_doc="x.htm",
        primary_doc_url="x",
    )
    fake_hit = SearchHit(
        ticker="NVDA",
        accession="acc-NVDA",
        form="10-K",
        filed="2026-02-21",
        section_label="business",
        section_title="Item 1",
        path="business",
        snippet="competitive advantage in AI accelerators...",
        score=5.0,
        citation="NVDA 10-K filed 2026-02-21 → business",
    )
    fake_lens = [LensView(dimension="moat", title="Moat & competitive position", hits=[fake_hit])]

    monkeypatch.setattr(write_mod, "fetch_fundamentals", lambda t: _fake_fundamentals(t))
    monkeypatch.setattr(write_mod, "list_indexed", lambda root, **kw: [fake_meta])
    monkeypatch.setattr(write_mod, "lens_view", lambda ticker, sec_root: fake_lens)

    rc = write_mod.run(_args("NVDA", no_lens=False, no_fundamentals=False))
    assert rc == 0
    content = (troot / "NVDA.md").read_text()
    assert "Moat & competitive position (DRAFT)" in content
    assert "NVDA 10-K filed 2026-02-21 → business" in content
    assert "competitive advantage in AI accelerators" in content


def test_run_no_lens_when_not_indexed(
    write_mod,
    roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(write_mod, "fetch_fundamentals", lambda t: _fake_fundamentals(t))
    monkeypatch.setattr(write_mod, "list_indexed", lambda root, **kw: [])
    monkeypatch.setattr(write_mod, "lens_view", lambda ticker, sec_root: [])

    troot, _ = roots
    rc = write_mod.run(_args("NVDA", no_lens=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "no indexed filings" in out
    # Evidence section is the TODO version
    content = (troot / "NVDA.md").read_text()
    assert "Numbered list of specific evidence" in content


def test_run_require_indexed_fails_when_not_indexed(
    write_mod,
    roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(write_mod, "fetch_fundamentals", lambda t: _fake_fundamentals(t))
    monkeypatch.setattr(write_mod, "list_indexed", lambda root, **kw: [])

    rc = write_mod.run(_args("NVDA", no_lens=False, require_indexed=True))
    assert rc == 1
    out = capsys.readouterr().out
    assert "THESIS_WRITE_ERROR" in out
    assert "not indexed" in out


# ---- helpers ---------------------------------------------------------------


def test_health_rows_includes_all_six_components(write_mod) -> None:
    rendered = write_mod._health_rows()
    for name in HEALTH_COMPONENT_NAMES:
        assert name in rendered


def test_health_rows_weights_sum_to_100(write_mod) -> None:
    """Defensive — the rendered template's weights must sum to 100."""
    import re

    rendered = write_mod._health_rows()
    weights = [int(m) for m in re.findall(r"\| (\d+)% \|", rendered)]
    assert sum(weights) == 100
