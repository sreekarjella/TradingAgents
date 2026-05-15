"""Paper trading broker — real prices, virtual execution, SQLite persistence.

Uses yfinance for price data (or Angel One when configured).
All orders are logged in SQLite, never sent to a real exchange.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

import yfinance as yf

from .broker import BrokerInterface, Holding, Order, PortfolioSnapshot

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("data/paper_portfolio.db")
_DEFAULT_CAPITAL = 10_00_000.0  # ₹10 Lakhs


class PaperBroker(BrokerInterface):
    """Paper trading broker backed by SQLite.

    Args:
        db_path: Path to SQLite database file.
        initial_capital: Starting virtual cash in INR.
    """

    def __init__(
        self,
        db_path: Path = _DEFAULT_DB_PATH,
        initial_capital: float = _DEFAULT_CAPITAL,
    ):
        self.db_path = Path(db_path)
        self.initial_capital = initial_capital
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # Database setup
    # ------------------------------------------------------------------

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """Yield a SQLite connection that is **always** closed on exit.

        Note: ``sqlite3.Connection``'s own ``__enter__`` / ``__exit__`` only
        commits or rolls back the transaction — it does NOT close the
        connection. Wrapping in our own context manager guarantees the
        underlying file descriptor is released, otherwise high-frequency
        callers (run_daily over many tickers) leak FDs until ulimit is hit.
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:  # commits on success, rolls back on exception
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    side TEXT CHECK(side IN ('BUY', 'SELL')) NOT NULL,
                    quantity INTEGER NOT NULL,
                    price REAL NOT NULL,
                    total_value REAL NOT NULL,
                    status TEXT CHECK(status IN ('FILLED', 'REJECTED')) NOT NULL,
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

            # Initialize cash if first run
            row = conn.execute(
                "SELECT value FROM config WHERE key = 'cash'"
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO config (key, value) VALUES ('cash', ?)",
                    (str(self.initial_capital),),
                )
                conn.execute(
                    "INSERT INTO config (key, value) VALUES ('initial_capital', ?)",
                    (str(self.initial_capital),),
                )
                logger.info(
                    "Paper portfolio initialized with ₹%s", f"{self.initial_capital:,.0f}"
                )

    # ------------------------------------------------------------------
    # Price data
    # ------------------------------------------------------------------

    def get_ltp(self, ticker: str) -> float:
        """Get last traded price via yfinance."""
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1d")
            if hist.empty:
                raise ValueError(f"No price data for {ticker}")
            return float(hist["Close"].iloc[-1])
        except Exception as e:
            logger.error("Failed to get LTP for %s: %s", ticker, e)
            raise

    # ------------------------------------------------------------------
    # Order execution (paper)
    # ------------------------------------------------------------------

    def place_order(
        self,
        ticker: str,
        quantity: int,
        side: str,
        price: Optional[float] = None,
        rationale: Optional[str] = None,
    ) -> Order:
        """Execute a paper trade at real market price."""
        side = side.upper()
        if side not in ("BUY", "SELL"):
            raise ValueError(f"Invalid side: {side}. Must be BUY or SELL.")
        if quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {quantity}")

        # Get real market price if not specified
        ltp = price or self.get_ltp(ticker)
        total_value = ltp * quantity

        with self._conn() as conn:
            cash = self._get_cash(conn)

            if side == "BUY":
                order = self._execute_buy(conn, ticker, quantity, ltp, total_value, cash, rationale)
            else:
                order = self._execute_sell(conn, ticker, quantity, ltp, total_value, cash, rationale)

        logger.info(
            "Paper %s: %s x%d @ ₹%.2f = ₹%.2f [%s]",
            side, ticker, quantity, ltp, total_value, order.status,
        )
        return order

    def _execute_buy(
        self, conn: sqlite3.Connection, ticker: str, quantity: int,
        price: float, total_value: float, cash: float, rationale: Optional[str],
    ) -> Order:
        if total_value > cash:
            return self._reject_order(conn, ticker, "BUY", quantity, price, total_value, rationale,
                                      f"Insufficient funds: need ₹{total_value:,.0f}, have ₹{cash:,.0f}")

        # Deduct cash
        conn.execute("UPDATE config SET value = ? WHERE key = 'cash'", (str(cash - total_value),))

        # Update holdings (weighted avg price)
        existing = conn.execute("SELECT * FROM holdings WHERE ticker = ?", (ticker,)).fetchone()
        if existing:
            new_qty = existing["quantity"] + quantity
            new_invested = existing["invested_value"] + total_value
            new_avg = new_invested / new_qty
            conn.execute(
                "UPDATE holdings SET quantity=?, avg_price=?, invested_value=? WHERE ticker=?",
                (new_qty, new_avg, new_invested, ticker),
            )
        else:
            conn.execute(
                "INSERT INTO holdings (ticker, quantity, avg_price, invested_value) VALUES (?,?,?,?)",
                (ticker, quantity, price, total_value),
            )

        return self._record_order(conn, ticker, "BUY", quantity, price, total_value, "FILLED", rationale)

    def _execute_sell(
        self, conn: sqlite3.Connection, ticker: str, quantity: int,
        price: float, total_value: float, cash: float, rationale: Optional[str],
    ) -> Order:
        existing = conn.execute("SELECT * FROM holdings WHERE ticker = ?", (ticker,)).fetchone()
        if not existing or existing["quantity"] < quantity:
            held = existing["quantity"] if existing else 0
            return self._reject_order(conn, ticker, "SELL", quantity, price, total_value, rationale,
                                      f"Insufficient shares: want to sell {quantity}, hold {held}")

        # Calculate realized P&L
        pnl = (price - existing["avg_price"]) * quantity

        # Update holdings
        new_qty = existing["quantity"] - quantity
        if new_qty == 0:
            conn.execute("DELETE FROM holdings WHERE ticker = ?", (ticker,))
        else:
            new_invested = existing["avg_price"] * new_qty
            conn.execute(
                "UPDATE holdings SET quantity=?, invested_value=? WHERE ticker=?",
                (new_qty, new_invested, ticker),
            )

        # Add cash back
        conn.execute("UPDATE config SET value = ? WHERE key = 'cash'", (str(cash + total_value),))

        return self._record_order(conn, ticker, "SELL", quantity, price, total_value, "FILLED", rationale, pnl)

    def _record_order(
        self, conn: sqlite3.Connection, ticker: str, side: str,
        quantity: int, price: float, total_value: float,
        status: str, rationale: Optional[str], pnl: Optional[float] = None,
    ) -> Order:
        cursor = conn.execute(
            "INSERT INTO orders (ticker, side, quantity, price, total_value, status, rationale, pnl) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (ticker, side, quantity, price, total_value, status, rationale, pnl),
        )
        return Order(
            order_id=str(cursor.lastrowid),
            ticker=ticker, side=side, quantity=quantity, price=price,
            total_value=total_value, status=status, rationale=rationale,
            pnl=pnl, timestamp=datetime.now().isoformat(),
        )

    def _reject_order(
        self, conn: sqlite3.Connection, ticker: str, side: str,
        quantity: int, price: float, total_value: float,
        rationale: Optional[str], reason: str,
    ) -> Order:
        logger.warning("Order REJECTED: %s %s x%d — %s", side, ticker, quantity, reason)
        return self._record_order(conn, ticker, side, quantity, price, total_value, "REJECTED", f"REJECTED: {reason}")

    # ------------------------------------------------------------------
    # Portfolio queries
    # ------------------------------------------------------------------

    def _get_cash(self, conn: sqlite3.Connection) -> float:
        row = conn.execute("SELECT value FROM config WHERE key = 'cash'").fetchone()
        return float(row["value"]) if row else 0.0

    def get_cash(self) -> float:
        with self._conn() as conn:
            return self._get_cash(conn)

    def get_holdings(self) -> list[Holding]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM holdings WHERE quantity > 0").fetchall()

        holdings = []
        for row in rows:
            try:
                current_price = self.get_ltp(row["ticker"])
                unrealized = (current_price - row["avg_price"]) * row["quantity"]
            except Exception:
                current_price = None
                unrealized = None

            holdings.append(Holding(
                ticker=row["ticker"],
                quantity=row["quantity"],
                avg_price=row["avg_price"],
                invested_value=row["invested_value"],
                current_price=current_price,
                unrealized_pnl=unrealized,
            ))
        return holdings

    def get_portfolio(self) -> PortfolioSnapshot:
        holdings = self.get_holdings()
        cash = self.get_cash()
        holdings_value = sum(
            (h.current_price or h.avg_price) * h.quantity for h in holdings
        )
        total = cash + holdings_value

        return PortfolioSnapshot(
            cash=cash,
            holdings_value=holdings_value,
            total_value=total,
            holdings=holdings,
        )

    def get_order_history(self, ticker: Optional[str] = None) -> list[Order]:
        with self._conn() as conn:
            if ticker:
                rows = conn.execute(
                    "SELECT * FROM orders WHERE ticker = ? ORDER BY created_at DESC", (ticker,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()

        return [
            Order(
                order_id=str(row["id"]), ticker=row["ticker"], side=row["side"],
                quantity=row["quantity"], price=row["price"], total_value=row["total_value"],
                status=row["status"], rationale=row["rationale"], pnl=row["pnl"],
                timestamp=row["created_at"],
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Daily snapshot
    # ------------------------------------------------------------------

    def take_daily_snapshot(self, benchmark_ticker: str = "^NSEI") -> dict:
        """Record end-of-day portfolio snapshot for P&L tracking."""
        portfolio = self.get_portfolio()
        today = datetime.now().strftime("%Y-%m-%d")

        # Benchmark value
        try:
            benchmark_value = self.get_ltp(benchmark_ticker)
        except Exception:
            benchmark_value = None

        with self._conn() as conn:
            # Get previous snapshot for daily return calc
            prev = conn.execute(
                "SELECT total_value, benchmark_value FROM daily_snapshots ORDER BY date DESC LIMIT 1"
            ).fetchone()

            daily_return = None
            benchmark_return = None
            if prev:
                prev_total = prev["total_value"]
                if prev_total > 0:
                    daily_return = ((portfolio.total_value - prev_total) / prev_total) * 100
                prev_bench = prev["benchmark_value"]
                if prev_bench and benchmark_value and prev_bench > 0:
                    benchmark_return = ((benchmark_value - prev_bench) / prev_bench) * 100

            conn.execute(
                "INSERT OR REPLACE INTO daily_snapshots "
                "(date, cash, holdings_value, total_value, daily_return_pct, benchmark_value, benchmark_return_pct) "
                "VALUES (?,?,?,?,?,?,?)",
                (today, portfolio.cash, portfolio.holdings_value, portfolio.total_value,
                 daily_return, benchmark_value, benchmark_return),
            )

        return {
            "date": today,
            "cash": portfolio.cash,
            "holdings_value": portfolio.holdings_value,
            "total_value": portfolio.total_value,
            "daily_return_pct": daily_return,
            "benchmark_return_pct": benchmark_return,
        }
