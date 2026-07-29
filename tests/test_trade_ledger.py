"""Tests for skills/clarion-portfolio-monitor/scripts/trade-ledger.py.

The FIFO lot replay (derive_positions) is pure computation over the
transactions table — testable offline against a throwaway DuckDB.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import duckdb
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    REPO_ROOT / "skills" / "clarion-portfolio-monitor" / "scripts" / "trade-ledger.py"
)


@pytest.fixture(scope="module")
def ledger_mod():
    spec = importlib.util.spec_from_file_location("clarion_trade_ledger", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["clarion_trade_ledger"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def con(ledger_mod):
    c = duckdb.connect(":memory:")
    c.execute(ledger_mod.DDL)
    yield c
    c.close()


_NEXT_ID = iter(range(1, 10_000))


def _fill(con, symbol: str, action: str, qty: float, price: float, ts: str) -> None:
    con.execute(
        "INSERT INTO transactions (id, transaction_type, symbol, action, quantity, price, executed_at)"
        " VALUES (?, 'Trade', ?, ?, ?, ?, ?)",
        [next(_NEXT_ID), symbol, action, qty, price, ts],
    )


def test_single_buy_opens_lot(ledger_mod, con):
    _fill(con, "AAPL", "Buy to Open", 10, 100.0, "2026-01-02 10:00:00")
    book = ledger_mod.derive_positions(con)
    st = book["AAPL"]
    assert st["qty"] == 10
    assert st["avg"] == 100.0
    assert st["realized"] == 0.0


def test_two_buys_weighted_average(ledger_mod, con):
    _fill(con, "AAPL", "Buy to Open", 10, 100.0, "2026-01-02 10:00:00")
    _fill(con, "AAPL", "Buy to Open", 10, 110.0, "2026-01-03 10:00:00")
    st = ledger_mod.derive_positions(con)["AAPL"]
    assert st["qty"] == 20
    assert st["avg"] == pytest.approx(105.0)


def test_partial_sell_relieves_fifo(ledger_mod, con):
    _fill(con, "AAPL", "Buy to Open", 10, 100.0, "2026-01-02 10:00:00")
    _fill(con, "AAPL", "Buy to Open", 10, 110.0, "2026-01-03 10:00:00")
    _fill(con, "AAPL", "Sell to Close", 5, 120.0, "2026-01-04 10:00:00")
    st = ledger_mod.derive_positions(con)["AAPL"]
    # FIFO: the 5 shares sold come from the $100 lot
    assert st["realized"] == pytest.approx((120.0 - 100.0) * 5)
    assert st["qty"] == 15
    assert st["avg"] == pytest.approx((5 * 100.0 + 10 * 110.0) / 15)


def test_full_close_realizes_and_zeroes(ledger_mod, con):
    _fill(con, "TLT", "Buy to Open", 8, 90.0, "2026-01-02 10:00:00")
    _fill(con, "TLT", "Sell to Close", 8, 95.0, "2026-02-01 10:00:00")
    st = ledger_mod.derive_positions(con)["TLT"]
    assert st["qty"] == 0
    assert st["avg"] == 0.0
    assert st["realized"] == pytest.approx(40.0)


def test_short_open_and_cover(ledger_mod, con):
    _fill(con, "XYZ", "Sell to Open", 10, 100.0, "2026-01-02 10:00:00")
    _fill(con, "XYZ", "Buy to Close", 10, 90.0, "2026-01-05 10:00:00")
    st = ledger_mod.derive_positions(con)["XYZ"]
    assert st["qty"] == 0
    assert st["realized"] == pytest.approx(100.0)  # (100 - 90) * 10 profit on short


def test_close_and_reopen_keeps_lots_separate(ledger_mod, con):
    _fill(con, "IREN", "Buy to Open", 5, 10.0, "2026-01-02 10:00:00")
    _fill(con, "IREN", "Sell to Close", 5, 12.0, "2026-01-10 10:00:00")
    _fill(con, "IREN", "Buy to Open", 3, 15.0, "2026-02-01 10:00:00")
    st = ledger_mod.derive_positions(con)["IREN"]
    assert st["realized"] == pytest.approx(10.0)
    assert st["qty"] == 3
    assert st["avg"] == pytest.approx(15.0)


def test_inception_env_override(monkeypatch):
    monkeypatch.setenv("CLARION_LEDGER_INCEPTION", "2025-03-15")
    spec = importlib.util.spec_from_file_location("ledger_inception_check", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert str(mod.INCEPTION) == "2025-03-15"
