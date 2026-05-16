#!/usr/bin/env python3
"""
Clarion Portfolio Monitor — TastyTrade fetch script.

Reads TASTYTRADE_CLIENT_SECRET and TASTYTRADE_REFRESH_TOKEN from environment,
authenticates via OAuth2, fetches account balances, open positions, today's
transactions, and 30-day NLV history. Writes a structured JSON snapshot and
a human-readable markdown summary.

Usage:
    python fetch.py [--json-only] [--account ACCOUNT_NUMBER] [--no-history]

Secrets (set in Zo Settings > Advanced > Secrets):
    TASTYTRADE_CLIENT_SECRET — OAuth app client secret
    TASTYTRADE_REFRESH_TOKEN  — generated refresh token (never expires)

Output:
    ~/clarion/portfolio/YYYY-MM-DD.json   Full raw data
    ~/clarion/portfolio/YYYY-MM-DD.md     Human-readable summary
    ~/clarion/portfolio/latest.json       Symlink to today's JSON
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

CLARION_DATA_ROOT = os.environ.get("CLARION_DATA_ROOT", "/home/workspace/clarion")
PORTFOLIO_DIR = Path(CLARION_DATA_ROOT) / "portfolio"

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)


def fmt_dollar(val):
    """Format a float/decimal as USD."""
    try:
        v = float(val)
        return f"${v:,.2f}"
    except (TypeError, ValueError):
        return str(val)


def fmt_pct(val):
    """Format a float/decimal as percentage."""
    try:
        return f"{float(val):+.2f}%"
    except (TypeError, ValueError):
        return str(val)


async def main():
    parser = argparse.ArgumentParser(description="Clarion Portfolio Monitor — fetch TastyTrade data")
    parser.add_argument("--json-only", action="store_true", help="Skip markdown summary")
    parser.add_argument("--account", type=str, help="Account number (auto-detects if omitted)")
    parser.add_argument("--no-history", action="store_true", help="Skip NLV history")
    args = parser.parse_args()

    client_secret = os.environ.get("TASTYTRADE_CLIENT_SECRET")
    refresh_token = os.environ.get("TASTYTRADE_REFRESH_TOKEN")

    if not client_secret:
        print("ERROR: TASTYTRADE_CLIENT_SECRET not set.", file=sys.stderr)
        print("Add it in Zo Settings > Advanced > Secrets.", file=sys.stderr)
        sys.exit(1)
    if not refresh_token:
        print("ERROR: TASTYTRADE_REFRESH_TOKEN not set.", file=sys.stderr)
        print("Add it in Zo Settings > Advanced > Secrets.", file=sys.stderr)
        sys.exit(1)

    try:
        from tastytrade import Session, Account
    except ImportError:
        print("Installing tastytrade SDK...", file=sys.stderr)
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "tastytrade", "-q"])
        from tastytrade import Session, Account

    print("Authenticating with TastyTrade...", file=sys.stderr)
    session = Session(client_secret, refresh_token)
    accounts = await Account.get(session)

    if not accounts:
        print("ERROR: No accounts found for this refresh token.", file=sys.stderr)
        sys.exit(1)

    target_account_number = args.account
    snapshot = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "fetched_at_local": datetime.now().isoformat(),
        "accounts": [],
    }

    for acct in accounts:
        acct_number = acct.account_number
        if target_account_number and acct_number != target_account_number:
            continue

        print(f"Fetching balances for {acct_number}...", file=sys.stderr)
        balances = await acct.get_balances(session)

        print(f"Fetching positions for {acct_number}...", file=sys.stderr)
        positions = await acct.get_positions(session)

        positions_data = []
        total_unrealized_pl = 0.0
        total_realized_day_pl = 0.0
        for pos in positions:
            qty = float(pos.quantity) if pos.quantity else 0
            if qty == 0:
                continue
            mark = float(pos.mark) if pos.mark else (float(pos.close_price) if pos.close_price else 0)
            cost = float(pos.average_open_price) if pos.average_open_price else 0
            multiplier = float(pos.multiplier) if pos.multiplier else 1
            direction = pos.quantity_direction or "Long"

            unrealized_pl = (mark - cost) * qty * multiplier
            if direction == "Short":
                unrealized_pl = -unrealized_pl
            realized_day = float(pos.realized_day_gain) if pos.realized_day_gain else 0
            total_unrealized_pl += unrealized_pl
            total_realized_day_pl += realized_day

            positions_data.append({
                "symbol": pos.symbol,
                "instrument_type": pos.instrument_type.value if hasattr(pos.instrument_type, 'value') else str(pos.instrument_type),
                "quantity": qty,
                "direction": direction,
                "mark_price": mark,
                "cost_basis": cost,
                "multiplier": multiplier,
                "unrealized_pl": round(unrealized_pl, 2),
                "unrealized_pl_pct": round((mark / cost - 1) * 100, 2) if cost > 0 else None,
                "realized_day_pl": round(realized_day, 2),
                "close_price": float(pos.close_price) if pos.close_price else None,
            })

        positions_data.sort(key=lambda p: abs(p["unrealized_pl"]), reverse=True)

        nlv = float(balances.net_liquidating_value) if balances.net_liquidating_value else 0
        cash = float(balances.cash_balance) if balances.cash_balance else 0
        buying_power = float(balances.equity_buying_power) if balances.equity_buying_power else 0
        margin_equity = float(balances.margin_equity) if balances.margin_equity else 0

        acct_data = {
            "account_number": acct_number,
            "balances": {
                "net_liquidating_value": round(nlv, 2),
                "cash_balance": round(cash, 2),
                "equity_buying_power": round(buying_power, 2),
                "margin_equity": round(margin_equity, 2),
                "available_trading_funds": round(float(balances.available_trading_funds), 2) if balances.available_trading_funds else 0,
                "maintenance_excess": round(float(balances.maintenance_excess), 2) if balances.maintenance_excess else 0,
            },
            "positions": positions_data,
            "position_count": len(positions_data),
            "total_unrealized_pl": round(total_unrealized_pl, 2),
            "total_realized_day_pl": round(total_realized_day_pl, 2),
            "total_pl_day": round(total_unrealized_pl + total_realized_day_pl, 2),
        }

        if not args.no_history:
            try:
                print(f"Fetching NLV history for {acct_number}...", file=sys.stderr)
                nl_history = await acct.get_net_liquidating_value_history(session, time_back="1m")
                nl_points = []
                for pt in nl_history[-30:]:
                    nl_points.append({
                        "time": pt.time.isoformat() if hasattr(pt.time, 'isoformat') else str(pt.time),
                        "close": float(pt.close) if pt.close else None,
                    })
                acct_data["nlv_history_30d"] = nl_points
            except Exception as e:
                print(f"Warning: NLV history fetch failed: {e}", file=sys.stderr)
                acct_data["nlv_history_30d"] = []

        try:
            print(f"Fetching today's transactions for {acct_number}...", file=sys.stderr)
            today = date.today()
            transactions = await acct.get_history(session, start_date=today)
            tx_data = []
            for tx in transactions:
                tx_data.append({
                    "id": tx.id,
                    "type": tx.transaction_type,
                    "sub_type": tx.transaction_sub_type,
                    "description": tx.description,
                    "symbol": tx.symbol,
                    "quantity": float(tx.quantity) if tx.quantity else 0,
                    "price": float(tx.price) if tx.price else None,
                    "value": float(tx.value) if tx.value else 0,
                    "net_value": float(tx.net_value) if tx.net_value else None,
                    "executed_at": tx.executed_at.isoformat() if hasattr(tx.executed_at, 'isoformat') else str(tx.executed_at),
                })
            acct_data["transactions_today"] = tx_data
        except Exception as e:
            print(f"Warning: Transactions fetch failed: {e}", file=sys.stderr)
            acct_data["transactions_today"] = []

        snapshot["accounts"].append(acct_data)

    PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)

    today_str = date.today().isoformat()
    json_path = PORTFOLIO_DIR / f"{today_str}.json"
    with open(json_path, "w") as f:
        json.dump(snapshot, f, cls=DecimalEncoder, indent=2)

    latest_link = PORTFOLIO_DIR / "latest.json"
    if latest_link.is_symlink() or latest_link.exists():
        latest_link.unlink()
    latest_link.symlink_to(json_path.name)

    print(f"\nSnapshot written to {json_path}", file=sys.stderr)

    if args.json_only:
        print(json.dumps(snapshot, cls=DecimalEncoder, indent=2))
        return

    md_path = PORTFOLIO_DIR / f"{today_str}.md"
    lines = []
    lines.append(f"# Portfolio Snapshot — {today_str}")
    lines.append(f"*Fetched {datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}*")
    lines.append("")

    for acct_data in snapshot["accounts"]:
        balances = acct_data["balances"]
        lines.append(f"## Account {acct_data['account_number']}")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|---|---|")
        lines.append(f"| Net Liquidating Value | {fmt_dollar(balances['net_liquidating_value'])} |")
        lines.append(f"| Cash Balance | {fmt_dollar(balances['cash_balance'])} |")
        lines.append(f"| Equity Buying Power | {fmt_dollar(balances['equity_buying_power'])} |")
        lines.append(f"| Margin Equity | {fmt_dollar(balances['margin_equity'])} |")
        lines.append(f"| Maintenance Excess | {fmt_dollar(balances['maintenance_excess'])} |")
        lines.append("")

        lines.append(f"**P/L Today:** {fmt_dollar(acct_data['total_pl_day'])} (unrealized: {fmt_dollar(acct_data['total_unrealized_pl'])}, realized: {fmt_dollar(acct_data['total_realized_day_pl'])})")
        lines.append("")

        if acct_data["positions"]:
            lines.append("### Open Positions")
            lines.append("")
            lines.append("| Symbol | Direction | Qty | Mark | Cost | Unrealized P/L | Day P/L |")
            lines.append("|---|---|---|---|---|---|---|")
            for pos in acct_data["positions"]:
                direction = "🔴 Short" if pos["direction"] == "Short" else "🟢 Long"
                lines.append(
                    f"| {pos['symbol']} | {direction} | {pos['quantity']:,.0f} | "
                    f"{fmt_dollar(pos['mark_price'])} | {fmt_dollar(pos['cost_basis'])} | "
                    f"{fmt_dollar(pos['unrealized_pl'])} ({fmt_pct(pos['unrealized_pl_pct'])}) | "
                    f"{fmt_dollar(pos['realized_day_pl'])} |"
                )
            lines.append("")
        else:
            lines.append("*No open positions.*")
            lines.append("")

        if acct_data.get("transactions_today"):
            lines.append("### Today's Transactions")
            lines.append("")
            for tx in acct_data["transactions_today"]:
                lines.append(f"- **{tx['type']}** — {tx['description']} ({fmt_dollar(tx['value'])})")
            lines.append("")

        if acct_data.get("nlv_history_30d") and len(acct_data["nlv_history_30d"]) >= 2:
            history = acct_data["nlv_history_30d"]
            first = history[0]["close"]
            last = history[-1]["close"]
            if first and last:
                change = last - first
                change_pct = (change / first) * 100
                lines.append(f"**30-Day NLV Change:** {fmt_dollar(change)} ({fmt_pct(change_pct)})")
                lines.append("")

    lines.append("---")
    lines.append(f"*Generated by Clarion Portfolio Monitor · {datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}*")

    with open(md_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Summary written to {md_path}", file=sys.stderr)
    print(f"\nSnapshot written to {json_path}")
    print(f"Summary written to {md_path}")


if __name__ == "__main__":
    asyncio.run(main())
