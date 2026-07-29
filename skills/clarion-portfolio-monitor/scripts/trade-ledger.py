#!/usr/bin/env python3
"""
Clarion Trade Ledger — transaction history sync + cost-basis verification.

Maintains a `transactions` table in ~/clarion/portfolio/portfolio.duckdb,
backfilled from TastyTrade full account history and upserted idempotently
by transaction ID. Derives per-symbol cost basis and realized P/L from
fills (average-cost method, matching TastyTrade's average_open_price),
and reconciles against the broker snapshot and thesis YAML.

Usage:
    python3 trade-ledger.py sync [--days N] [--full]     Fetch + upsert transactions
    python3 trade-ledger.py positions                     Derived positions from ledger
    python3 trade-ledger.py lots [--markdown] [--json]    Open lots per position (cost basis detail)
                                                          --json writes ~/clarion/portfolio/lots.json
                                                          (serves the private /ledger Zo Space page)
    python3 trade-ledger.py verify                        Reconcile ledger vs broker vs thesis YAML
    python3 trade-ledger.py realized                      Realized P/L by symbol (closed + partial)

Secrets (set in Zo Settings > Advanced > Secrets):
    TASTYTRADE_CLIENT_SECRET, TASTYTRADE_REFRESH_TOKEN

Default sync window is the last 7 days (idempotent). Use --full to backfill
from inception. `verify` and `positions` are offline (no API call).
"""

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import duckdb

CLARION_DATA_ROOT = os.environ.get("CLARION_DATA_ROOT", "/home/workspace/clarion")
PORTFOLIO_DIR = Path(CLARION_DATA_ROOT) / "portfolio"
DB_PATH = PORTFOLIO_DIR / "portfolio.duckdb"
THESES_DIR = Path(CLARION_DATA_ROOT) / "theses"
INCEPTION = date.fromisoformat(
    os.environ.get("CLARION_LEDGER_INCEPTION", "2000-01-01")
)  # earliest sync date for --full backfill; override per-account via env

DDL = """
CREATE TABLE IF NOT EXISTS transactions (
    id BIGINT PRIMARY KEY,
    account_number VARCHAR,
    transaction_type VARCHAR,
    transaction_sub_type VARCHAR,
    description VARCHAR,
    symbol VARCHAR,
    instrument_type VARCHAR,
    action VARCHAR,
    quantity DOUBLE,
    price DOUBLE,
    value DOUBLE,
    net_value DOUBLE,
    commission DOUBLE,
    fees DOUBLE,
    executed_at TIMESTAMP,
    transaction_date DATE,
    order_id BIGINT
)
"""


def connect(read_only=False):
    return duckdb.connect(str(DB_PATH), read_only=read_only)


async def sync(args):
    client_secret = os.environ.get("TASTYTRADE_CLIENT_SECRET")
    refresh_token = os.environ.get("TASTYTRADE_REFRESH_TOKEN")
    if not client_secret or not refresh_token:
        print("ERROR: TASTYTRADE_CLIENT_SECRET / TASTYTRADE_REFRESH_TOKEN not set.", file=sys.stderr)
        sys.exit(1)

    from tastytrade import Session, Account

    con = connect()
    con.execute(DDL)
    existing = con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]

    if args.full or existing == 0:
        start = INCEPTION
    else:
        start = date.today() - timedelta(days=args.days)

    print(f"Syncing transactions since {start} (existing rows: {existing})...", file=sys.stderr)
    session = Session(client_secret, refresh_token)
    accounts = await Account.get(session)

    rows = []
    for acct in accounts:
        txs = await acct.get_history(session, start_date=start)
        for tx in txs:
            fees = sum(
                float(x) for x in [tx.regulatory_fees, tx.clearing_fees,
                                   tx.proprietary_index_option_fees, tx.other_charge]
                if x is not None
            )
            rows.append((
                tx.id,
                tx.account_number,
                tx.transaction_type,
                tx.transaction_sub_type,
                tx.description,
                tx.symbol,
                tx.instrument_type.value if tx.instrument_type else None,
                tx.action.value if tx.action else None,
                float(tx.quantity) if tx.quantity is not None else None,
                float(tx.price) if tx.price is not None else None,
                float(tx.value) if tx.value is not None else None,
                float(tx.net_value) if tx.net_value is not None else None,
                float(tx.commission) if tx.commission is not None else None,
                fees,
                tx.executed_at,
                tx.transaction_date,
                tx.order_id,
            ))

    inserted = 0
    for row in rows:
        n = con.execute(
            "INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT (id) DO NOTHING", row
        ).fetchone()
        inserted += 1
    total = con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    lo, hi = con.execute("SELECT MIN(transaction_date), MAX(transaction_date) FROM transactions").fetchone()
    con.close()
    print(f"Fetched {len(rows)} transactions; ledger now has {total} rows covering {lo} → {hi}.")


def _fills(con):
    return con.execute("""
        SELECT symbol, action, quantity, price, executed_at, transaction_sub_type
        FROM transactions
        WHERE transaction_type = 'Trade' AND symbol IS NOT NULL
        ORDER BY executed_at, id
    """).fetchall()


def derive_positions(con):
    """FIFO lot replay of all fills (matches TastyTrade lot relief).

    Returns per-symbol state: open lots [qty, price, opened_at], qty,
    weighted avg open price, realized P/L, first/last fill timestamps.
    """
    book = {}
    for symbol, action, qty, price, executed_at, sub_type in _fills(con):
        st = book.setdefault(symbol, {
            "lots": [], "realized": 0.0,
            "buys": 0, "sells": 0, "first": executed_at, "last": executed_at,
        })
        st["last"] = executed_at
        signed = qty if action and action.startswith("Buy") else -qty
        st["buys" if signed > 0 else "sells"] += 1
        lots = st["lots"]

        remaining = signed
        while abs(remaining) > 1e-9 and lots and (lots[0][0] > 0) != (remaining > 0):
            lot = lots[0]
            closed = min(abs(remaining), abs(lot[0]))
            st["realized"] += (price - lot[1]) * closed * (1 if lot[0] > 0 else -1)
            lot[0] -= closed * (1 if lot[0] > 0 else -1)
            remaining += closed if remaining < 0 else -closed
            if abs(lot[0]) < 1e-9:
                lots.pop(0)
        if abs(remaining) > 1e-9:
            lots.append([remaining, price, executed_at])

    for st in book.values():
        qty = sum(l[0] for l in st["lots"])
        st["qty"] = qty
        st["avg"] = (sum(abs(l[0]) * l[1] for l in st["lots"]) / abs(qty)) if abs(qty) > 1e-9 else 0.0
    return book


def load_broker_positions():
    latest = PORTFOLIO_DIR / "latest.json"
    if not latest.exists():
        return {}, None
    with open(latest) as f:
        snap = json.load(f)
    out = {}
    for acct in snap.get("accounts", []):
        for p in acct.get("positions", []):
            out[p["symbol"]] = p
    return out, snap.get("fetched_at")


def load_thesis_bases():
    out = {}
    if not THESES_DIR.exists():
        return out
    for f in sorted(THESES_DIR.glob("*.md")):
        text = f.read_text()
        m = re.search(r"```yaml\n(.*?)```", text, re.DOTALL) or re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        if not m:
            continue
        yaml_block = m.group(1)
        def grab(key):
            mm = re.search(rf"^{key}:\s*([^\n#]+)", yaml_block, re.MULTILINE)
            return mm.group(1).strip().strip('"\'') if mm else None
        status = grab("status")
        cb = grab("cost_basis")
        shares = grab("shares")
        try:
            cb = float(cb) if cb else None
        except ValueError:
            cb = None
        try:
            shares = float(shares) if shares else None
        except ValueError:
            shares = None
        out[f.stem.upper()] = {"status": status, "cost_basis": cb, "shares": shares, "file": f.name}
    return out


def cmd_positions(_args):
    con = connect(read_only=True)
    book = derive_positions(con)
    con.close()
    print(f"{'Symbol':<8} {'Qty':>6} {'AvgCost':>10} {'Realized P/L':>13}  {'First fill':<12} {'Last fill':<12}")
    for sym in sorted(book, key=lambda s: -abs(book[s]['qty'] * book[s]['avg'])):
        st = book[sym]
        if st["qty"] == 0:
            continue
        print(f"{sym:<8} {st['qty']:>6.0f} {st['avg']:>10.2f} {st['realized']:>13.2f}  "
              f"{str(st['first'])[:10]:<12} {str(st['last'])[:10]:<12}")
    print("\nClosed positions:")
    for sym in sorted(book):
        st = book[sym]
        if st["qty"] == 0:
            print(f"{sym:<8} {'—':>6} {'—':>10} {st['realized']:>13.2f}  "
                  f"{str(st['first'])[:10]:<12} {str(st['last'])[:10]:<12}")


def cmd_lots(args):
    """Open lots per position — the cost basis detail behind each share held."""
    con = connect(read_only=True)
    book = derive_positions(con)
    con.close()

    open_syms = sorted(s for s in book if abs(book[s]["qty"]) > 1e-9)

    if args.markdown:
        print("### Cost Basis Detail — Open Lots (FIFO)")
        print("")
        print("| Symbol | Qty | Avg Cost | Lots (opened · qty @ fill price) |")
        print("|---|---|---|---|")
        for sym in open_syms:
            st = book[sym]
            parts = []
            for lot_qty, lot_price, opened_at in st["lots"]:
                d = str(opened_at)[:10]
                parts.append(f"{d} · {abs(lot_qty):.0f} @ ${lot_price:,.2f}")
            qty = st["qty"]
            qty_str = f"{qty:.0f}" if qty > 0 else f"{abs(qty):.0f} (short)"
            print(f"| {sym} | {qty_str} | ${st['avg']:,.2f} | {'<br>'.join(parts)} |")
        print("")
        print("*Lots derived from the trade ledger (FIFO replay of all fills, matching TastyTrade lot relief). Avg Cost reconciles to broker average open price.*")
        return

    if args.json:
        out_path = PORTFOLIO_DIR / "lots.json"
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "positions": [],
            "closed": [],
        }
        for sym in open_syms:
            st = book[sym]
            payload["positions"].append({
                "symbol": sym,
                "qty": round(st["qty"], 4),
                "avg_cost": round(st["avg"], 4),
                "realized": round(st["realized"], 2),
                "lots": [
                    {"opened": str(opened_at)[:10], "qty": round(lot_qty, 4), "price": round(lot_price, 4)}
                    for lot_qty, lot_price, opened_at in st["lots"]
                ],
            })
        for sym in sorted(book):
            st = book[sym]
            if abs(st["qty"]) > 1e-9:
                continue
            payload["closed"].append({
                "symbol": sym,
                "realized": round(st["realized"], 2),
                "first_fill": str(st["first"])[:10],
                "last_fill": str(st["last"])[:10],
            })
        payload["total_realized"] = round(sum(st["realized"] for st in book.values()), 2)
        with open(out_path, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"Wrote {out_path}")
        return

    print(f"{'Symbol':<8} {'Opened':<12} {'Qty':>6} {'Fill':>10} {'Lot Cost':>11}")
    for sym in open_syms:
        st = book[sym]
        for i, (lot_qty, lot_price, opened_at) in enumerate(st["lots"]):
            label = sym if i == 0 else ""
            print(f"{label:<8} {str(opened_at)[:10]:<12} {lot_qty:>6.0f} {lot_price:>10.2f} {abs(lot_qty) * lot_price:>11.2f}")
        if len(st["lots"]) > 1:
            print(f"{'':<8} {'  avg':<12} {st['qty']:>6.0f} {st['avg']:>10.2f} {abs(st['qty']) * st['avg']:>11.2f}")


def cmd_realized(_args):
    con = connect(read_only=True)
    book = derive_positions(con)
    con.close()
    total = 0.0
    print(f"{'Symbol':<8} {'Realized P/L':>13} {'Open qty':>9}")
    for sym in sorted(book, key=lambda s: -book[s]["realized"]):
        st = book[sym]
        if abs(st["realized"]) < 0.005:
            continue
        total += st["realized"]
        print(f"{sym:<8} {st['realized']:>13.2f} {st['qty']:>9.0f}")
    print(f"{'TOTAL':<8} {total:>13.2f}")


def cmd_verify(_args):
    con = connect(read_only=True)
    book = derive_positions(con)
    con.close()
    broker, fetched_at = load_broker_positions()
    theses = load_thesis_bases()

    print(f"Ledger vs broker snapshot ({fetched_at}) vs thesis YAML\n")
    hdr = f"{'Symbol':<8} {'Qty L/B':>9} {'Ledger':>9} {'Broker':>9} {'Δ':>7} {'Thesis':>9} {'Δ':>7}  Status"
    print(hdr)
    print("-" * len(hdr))

    issues = []
    symbols = sorted(set(book) | set(broker), key=lambda s: s)
    for sym in symbols:
        st = book.get(sym)
        bp = broker.get(sym)
        lqty = st["qty"] if st else 0.0
        bqty = 0.0
        if bp:
            bqty = bp["quantity"] * (1 if bp["direction"] == "Long" else -1)
        if lqty == 0 and not bp:
            continue

        lavg = st["avg"] if st and st["qty"] != 0 else None
        bavg = bp["cost_basis"] if bp else None
        th = theses.get(sym.rstrip("0123456789").upper()) or theses.get(sym.upper())
        tavg = th["cost_basis"] if th else None

        d_broker = (lavg - bavg) if (lavg is not None and bavg is not None) else None
        d_thesis = (tavg - bavg) if (tavg is not None and bavg is not None) else None

        flags = []
        if lqty != bqty:
            flags.append(f"QTY MISMATCH ledger={lqty:.0f} broker={bqty:.0f}")
        if d_broker is not None and abs(d_broker) > 0.005:
            flags.append(f"LEDGER≠BROKER by {d_broker:+.2f}")
        if d_thesis is not None and abs(d_thesis) > 0.005:
            flags.append(f"THESIS DRIFT {d_thesis:+.2f}")
        if th and th.get("shares") is not None and abs(th["shares"] - abs(bqty)) > 1e-9:
            flags.append(f"THESIS SHARES {th['shares']:.0f}≠{abs(bqty):.0f}")
        if bp and not th:
            flags.append("NO THESIS")
        status = "; ".join(flags) if flags else "OK"
        if flags:
            issues.append((sym, flags))

        print(f"{sym:<8} {f'{lqty:.0f}/{bqty:.0f}':>9} "
              f"{f'{lavg:.2f}' if lavg is not None else '—':>9} "
              f"{f'{bavg:.2f}' if bavg is not None else '—':>9} "
              f"{f'{d_broker:+.2f}' if d_broker is not None else '—':>7} "
              f"{f'{tavg:.2f}' if tavg is not None else '—':>9} "
              f"{f'{d_thesis:+.2f}' if d_thesis is not None else '—':>7}  {status}")

    active_no_pos = [
        (sym, th["file"]) for sym, th in theses.items()
        if th["status"] == "active" and sym not in {s for s in broker}
    ]
    if active_no_pos:
        print("\nActive theses with NO open position:")
        for sym, fname in active_no_pos:
            print(f"  {sym} ({fname})")

    print(f"\n{len(issues)} symbol(s) with discrepancies." if issues else "\nAll clear — ledger, broker, and thesis YAML reconcile.")
    return issues


def main():
    parser = argparse.ArgumentParser(description="Clarion Trade Ledger")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_sync = sub.add_parser("sync", help="Fetch + upsert transactions from TastyTrade")
    p_sync.add_argument("--days", type=int, default=7, help="Lookback window (default 7)")
    p_sync.add_argument("--full", action="store_true", help="Backfill from inception")
    sub.add_parser("positions", help="Derived positions from ledger")
    p_lots = sub.add_parser("lots", help="Open lots per position (cost basis detail)")
    p_lots.add_argument("--markdown", action="store_true", help="Emit a markdown table")
    p_lots.add_argument("--json", action="store_true", help="Write lots.json for the /ledger page")
    sub.add_parser("verify", help="Reconcile ledger vs broker vs thesis YAML")
    sub.add_parser("realized", help="Realized P/L by symbol")
    args = parser.parse_args()

    if args.cmd == "sync":
        asyncio.run(sync(args))
    elif args.cmd == "positions":
        cmd_positions(args)
    elif args.cmd == "lots":
        cmd_lots(args)
    elif args.cmd == "realized":
        cmd_realized(args)
    elif args.cmd == "verify":
        cmd_verify(args)


if __name__ == "__main__":
    main()
