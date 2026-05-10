"""Seed demo data for the Trading Dashboard.

Populates paper_portfolio.db and run_tracker.db with 30 days of
realistic Indian stock market data for demo/presentation purposes.

Usage:
    python -m dashboard.seed_demo_data          # seeds demo DBs
    python -m dashboard.seed_demo_data --reset   # wipe & reseed
"""

from __future__ import annotations

import random
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data"
PORTFOLIO_DB = DATA_DIR / "paper_portfolio.db"
RUN_TRACKER_DB = DATA_DIR / "run_tracker.db"

# ---------------------------------------------------------------------------
# NIFTY 50 stocks with realistic price ranges (May 2026 ballpark)
# ---------------------------------------------------------------------------
STOCKS: dict[str, dict[str, float]] = {
    "RELIANCE.NS":  {"price": 1435.0, "vol": 0.018},
    "TCS.NS":       {"price": 3850.0, "vol": 0.015},
    "HDFCBANK.NS":  {"price": 1680.0, "vol": 0.016},
    "INFY.NS":      {"price": 1520.0, "vol": 0.020},
    "ICICIBANK.NS": {"price": 1120.0, "vol": 0.017},
    "HINDUNILVR.NS":{"price": 2340.0, "vol": 0.012},
    "BHARTIARTL.NS":{"price": 1180.0, "vol": 0.019},
    "ITC.NS":       {"price": 445.0,  "vol": 0.013},
}

INITIAL_CAPITAL = 1_000_000.0
RATINGS = ["Buy", "Strong Buy", "Hold", "Sell", "Overweight", "Underweight"]


def ensure_tables(conn: sqlite3.Connection, db_type: str) -> None:
    """Create tables if they don't exist."""
    if db_type == "portfolio":
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                side TEXT CHECK(side IN ('BUY','SELL')) NOT NULL,
                quantity INTEGER NOT NULL,
                price REAL NOT NULL,
                total_value REAL NOT NULL,
                status TEXT CHECK(status IN ('FILLED','REJECTED')) NOT NULL,
                rationale TEXT,
                pnl REAL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS holdings (
                ticker TEXT PRIMARY KEY,
                quantity INTEGER NOT NULL DEFAULT 0,
                avg_price REAL NOT NULL DEFAULT 0,
                invested_value REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS daily_snapshots (
                date TEXT PRIMARY KEY,
                cash REAL NOT NULL,
                holdings_value REAL NOT NULL,
                total_value REAL NOT NULL,
                daily_return_pct REAL,
                benchmark_value REAL,
                benchmark_return_pct REAL
            );
        """)
    else:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS run_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                date TEXT NOT NULL,
                rating TEXT NOT NULL DEFAULT '',
                trade_side TEXT,
                trade_qty INTEGER NOT NULL DEFAULT 0,
                duration_secs REAL NOT NULL DEFAULT 0,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_run_log_date_ticker
                ON run_log (date, ticker);
        """)


def wipe(conn: sqlite3.Connection, tables: list[str]) -> None:
    """Delete all rows from given tables."""
    for t in tables:
        conn.execute(f"DELETE FROM {t}")  # noqa: S608
    conn.commit()


def simulate_price_path(
    start_price: float, days: int, daily_vol: float, drift: float = 0.0003
) -> list[float]:
    """Generate a geometric-Brownian-motion–style price path."""
    prices = [start_price]
    for _ in range(days - 1):
        ret = drift + daily_vol * random.gauss(0, 1)
        prices.append(prices[-1] * (1 + ret))
    return prices


def seed_portfolio_db(reset: bool = False) -> None:
    """Populate paper_portfolio.db with demo data."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(PORTFOLIO_DB))
    ensure_tables(conn, "portfolio")

    if reset:
        wipe(conn, ["orders", "holdings", "daily_snapshots", "config"])

    random.seed(42)
    num_days = 30
    today = date.today()
    start_date = today - timedelta(days=num_days - 1)

    # Pick 6 stocks to hold
    held_tickers = random.sample(list(STOCKS.keys()), 6)

    # Generate price paths
    price_paths: dict[str, list[float]] = {}
    for ticker in STOCKS:
        info = STOCKS[ticker]
        path = simulate_price_path(info["price"], num_days, info["vol"])
        price_paths[ticker] = path

    # Build orders over 30 days
    cash = INITIAL_CAPITAL
    portfolio: dict[str, dict[str, float]] = {}  # ticker -> {qty, avg_price, invested}
    orders: list[dict] = []
    daily_data: list[dict] = []

    # NIFTY benchmark (start ~22000, ~12% annualized ≈ 0.045%/day)
    benchmark_start = 22000.0
    benchmark_path = simulate_price_path(benchmark_start, num_days, 0.012, 0.0004)

    for day_idx in range(num_days):
        current_date = start_date + timedelta(days=day_idx)
        if current_date.weekday() >= 5:  # skip weekends
            continue

        day_str = current_date.isoformat()
        dt_str = f"{day_str} {random.randint(9,15):02d}:{random.randint(0,59):02d}:{random.randint(0,59):02d}"

        # Decide if we trade today (70% chance)
        if random.random() < 0.70 or day_idx < 3:
            # Pick 1-2 tickers to trade
            num_trades = random.choice([1, 1, 2])
            trade_tickers = random.sample(held_tickers, min(num_trades, len(held_tickers)))

            for ticker in trade_tickers:
                price = price_paths[ticker][day_idx]
                price = round(price * (1 + random.uniform(-0.005, 0.005)), 2)

                # Decide BUY vs SELL
                has_holding = ticker in portfolio and portfolio[ticker]["qty"] > 0
                side = "SELL" if has_holding and random.random() < 0.25 else "BUY"

                if side == "BUY":
                    alloc_pct = random.uniform(0.02, 0.06)
                    qty = max(1, int(cash * alloc_pct / price))
                    total = round(qty * price, 2)

                    # Occasionally reject
                    if random.random() < 0.08:
                        status = "REJECTED"
                        rationale = f"Rejected: insufficient margin for {ticker}"
                        orders.append({
                            "ticker": ticker, "side": "BUY", "quantity": qty,
                            "price": price, "total_value": total, "status": status,
                            "rationale": rationale, "pnl": None, "created_at": dt_str,
                        })
                        continue

                    cash -= total
                    if ticker not in portfolio:
                        portfolio[ticker] = {"qty": 0, "avg_price": 0.0, "invested": 0.0}
                    old_qty = portfolio[ticker]["qty"]
                    old_invested = portfolio[ticker]["invested"]
                    portfolio[ticker]["qty"] = old_qty + qty
                    portfolio[ticker]["invested"] = old_invested + total
                    portfolio[ticker]["avg_price"] = portfolio[ticker]["invested"] / portfolio[ticker]["qty"]

                    rating = random.choice(["Buy", "Strong Buy", "Overweight"])
                    rationale = f"{rating} {ticker} — allocating {alloc_pct*100:.0f}% of portfolio. Buying {qty} shares @ ₹{price:,.2f} = ₹{total:,.0f}."
                    orders.append({
                        "ticker": ticker, "side": "BUY", "quantity": qty,
                        "price": price, "total_value": total, "status": "FILLED",
                        "rationale": rationale, "pnl": None, "created_at": dt_str,
                    })
                else:
                    # SELL portion
                    hold_qty = int(portfolio[ticker]["qty"])
                    sell_qty = max(1, int(hold_qty * random.uniform(0.3, 0.7)))
                    total = round(sell_qty * price, 2)
                    avg = portfolio[ticker]["avg_price"]
                    pnl = round((price - avg) * sell_qty, 2)

                    cash += total
                    portfolio[ticker]["qty"] -= sell_qty
                    portfolio[ticker]["invested"] = portfolio[ticker]["qty"] * avg
                    if portfolio[ticker]["qty"] <= 0:
                        del portfolio[ticker]

                    rating = random.choice(["Sell", "Underweight"])
                    rationale = f"{rating} {ticker} — trimming position. Selling {sell_qty} shares @ ₹{price:,.2f}. P&L: ₹{pnl:,.0f}."
                    orders.append({
                        "ticker": ticker, "side": "SELL", "quantity": sell_qty,
                        "price": price, "total_value": total, "status": "FILLED",
                        "rationale": rationale, "pnl": pnl, "created_at": dt_str,
                    })

        # Daily snapshot
        holdings_value = 0.0
        for t, h in portfolio.items():
            p = price_paths[t][day_idx]
            holdings_value += h["qty"] * p

        total_value = cash + holdings_value
        prev_total = daily_data[-1]["total_value"] if daily_data else INITIAL_CAPITAL
        daily_ret = ((total_value - prev_total) / prev_total * 100) if prev_total else 0
        bm_val = benchmark_path[day_idx]
        prev_bm = daily_data[-1]["benchmark_value"] if daily_data else benchmark_start
        bm_ret = ((bm_val - prev_bm) / prev_bm * 100) if prev_bm else 0

        daily_data.append({
            "date": day_str, "cash": round(cash, 2),
            "holdings_value": round(holdings_value, 2),
            "total_value": round(total_value, 2),
            "daily_return_pct": round(daily_ret, 4),
            "benchmark_value": round(bm_val, 2),
            "benchmark_return_pct": round(bm_ret, 4),
        })

    # Insert orders
    for o in orders:
        conn.execute(
            "INSERT INTO orders (ticker,side,quantity,price,total_value,status,rationale,pnl,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (o["ticker"], o["side"], o["quantity"], o["price"], o["total_value"],
             o["status"], o["rationale"], o["pnl"], o["created_at"]),
        )

    # Insert holdings
    for ticker, h in portfolio.items():
        conn.execute(
            "INSERT OR REPLACE INTO holdings (ticker, quantity, avg_price, invested_value) "
            "VALUES (?,?,?,?)",
            (ticker, int(h["qty"]), round(h["avg_price"], 2), round(h["invested"], 2)),
        )

    # Insert daily snapshots
    for snap in daily_data:
        conn.execute(
            "INSERT OR REPLACE INTO daily_snapshots "
            "(date,cash,holdings_value,total_value,daily_return_pct,benchmark_value,benchmark_return_pct) "
            "VALUES (?,?,?,?,?,?,?)",
            (snap["date"], snap["cash"], snap["holdings_value"], snap["total_value"],
             snap["daily_return_pct"], snap["benchmark_value"], snap["benchmark_return_pct"]),
        )

    # Config
    conn.execute("INSERT OR REPLACE INTO config (key,value) VALUES ('cash',?)", (str(round(cash, 2)),))
    conn.execute("INSERT OR REPLACE INTO config (key,value) VALUES ('initial_capital',?)", (str(INITIAL_CAPITAL),))

    conn.commit()
    conn.close()
    print(f"✅ Seeded paper_portfolio.db: {len(orders)} orders, "
          f"{len(portfolio)} holdings, {len(daily_data)} snapshots")


def seed_run_tracker_db(reset: bool = False) -> None:
    """Populate run_tracker.db with demo run_log entries."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(RUN_TRACKER_DB))
    ensure_tables(conn, "run_tracker")

    if reset:
        wipe(conn, ["run_log"])

    random.seed(99)
    today = date.today()
    tickers = list(STOCKS.keys())
    entries: list[dict] = []

    # Spread runs across the last 5 days
    for day_offset in range(5):
        run_date = today - timedelta(days=day_offset)
        if run_date.weekday() >= 5:
            continue

        day_str = run_date.isoformat()
        # 3-6 tickers analyzed per day
        day_tickers = random.sample(tickers, random.randint(3, 6))

        for ticker in day_tickers:
            duration = round(random.uniform(45, 280), 1)
            rating = random.choice(RATINGS)
            error = None

            # 10% chance of error
            if random.random() < 0.10:
                error = random.choice([
                    "Timeout fetching market data",
                    "LLM rate limit exceeded",
                    "Duplicate ticker — already analyzed today",
                    "yfinance API error: 429 Too Many Requests",
                ])
                if "Duplicate" in error:
                    rating = "Duplicate"

            trade_side = None
            trade_qty = 0
            if not error:
                if rating in ("Buy", "Strong Buy", "Overweight"):
                    trade_side = "BUY"
                    trade_qty = random.randint(5, 50)
                elif rating in ("Sell",):
                    trade_side = "SELL"
                    trade_qty = random.randint(5, 30)

            hour = random.randint(9, 16)
            minute = random.randint(0, 59)
            second = random.randint(0, 59)
            created_at = f"{day_str} {hour:02d}:{minute:02d}:{second:02d}"

            entries.append({
                "ticker": ticker, "date": day_str, "rating": rating,
                "trade_side": trade_side, "trade_qty": trade_qty,
                "duration_secs": duration, "error": error,
                "created_at": created_at,
            })

    for e in entries:
        conn.execute(
            "INSERT INTO run_log (ticker,date,rating,trade_side,trade_qty,duration_secs,error,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (e["ticker"], e["date"], e["rating"], e["trade_side"],
             e["trade_qty"], e["duration_secs"], e["error"], e["created_at"]),
        )

    conn.commit()
    conn.close()
    print(f"✅ Seeded run_tracker.db: {len(entries)} run_log entries across "
          f"{len({e['date'] for e in entries})} days")


def seed_all(reset: bool = True) -> str:
    """Seed both DBs. Returns summary message. Called by API endpoint."""
    seed_portfolio_db(reset=reset)
    seed_run_tracker_db(reset=reset)
    return "Demo data loaded: orders, holdings, snapshots, and run logs seeded."


def main() -> None:
    """Entrypoint."""
    reset = "--reset" in sys.argv
    if reset:
        print("🔄 Resetting databases before seeding…")

    seed_portfolio_db(reset=reset)
    seed_run_tracker_db(reset=reset)
    print("\n🎉 Demo data seeded! Start the dashboard:")
    print("   cd TradingAgents && python -m dashboard.app")


if __name__ == "__main__":
    main()
