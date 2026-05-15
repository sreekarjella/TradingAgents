"""Run tracker — prevents duplicate analysis and trades within the same day.

Tracks which tickers have been analyzed (and with what result) in a
lightweight SQLite table.  The daily_runner checks this before spending
15 minutes on a pipeline run.

Usage::

    tracker = RunTracker()                      # default DB
    tracker = RunTracker(Path("data/runs.db"))   # custom path

    if tracker.was_analyzed_today("RELIANCE.NS"):
        print("Already done today — skipping")
    else:
        result = run_pipeline(...)
        tracker.log_run("RELIANCE.NS", "Buy", duration=842.3)

    # List today's runs
    for run in tracker.today_runs():
        print(f"{run.ticker}: {run.rating} ({run.duration_secs:.0f}s)")

    # Force re-analysis (e.g. manual override)
    tracker.clear_today("RELIANCE.NS")
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("data/run_tracker.db")


@dataclass(frozen=True)
class RunRecord:
    """Record of a single pipeline analysis run."""

    id: int
    ticker: str
    date: str
    rating: str
    trade_side: Optional[str]   # BUY, SELL, or None (Hold/Skip)
    trade_qty: int
    duration_secs: float
    error: Optional[str]
    created_at: str


class RunTracker:
    """Tracks pipeline runs per ticker per day to prevent duplicates.

    Uses a separate SQLite database from the paper broker so it works
    with both paper and live trading modes.
    """

    def __init__(self, db_path: Path = _DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """Yield a SQLite connection that is **always** closed on exit.

        See PaperBroker._conn for the rationale: sqlite3.Connection's own
        context manager only commits/rolls back — it does not close.
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
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
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_run_log_date_ticker
                ON run_log (date, ticker)
            """)

    def was_analyzed_today(
        self, ticker: str, date: Optional[str] = None,
    ) -> bool:
        """Check if a ticker was already analyzed today.

        Args:
            ticker: Stock ticker (e.g. ``RELIANCE.NS``).
            date: Override date (YYYY-MM-DD). Defaults to today.

        Returns:
            True if a successful run exists for this ticker today.
        """
        date = date or datetime.now().strftime("%Y-%m-%d")
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM run_log WHERE ticker = ? AND date = ? AND error IS NULL LIMIT 1",
                (ticker, date),
            ).fetchone()
        return row is not None

    def log_run(
        self,
        ticker: str,
        rating: str = "",
        trade_side: Optional[str] = None,
        trade_qty: int = 0,
        duration_secs: float = 0.0,
        error: Optional[str] = None,
        date: Optional[str] = None,
    ) -> None:
        """Record a pipeline analysis run.

        Args:
            ticker: Stock ticker.
            rating: Pipeline rating (Buy/Hold/Sell/etc).
            trade_side: BUY, SELL, or None.
            trade_qty: Shares traded (0 if skipped).
            duration_secs: How long the pipeline took.
            error: Error message if the run failed.
            date: Override date. Defaults to today.
        """
        date = date or datetime.now().strftime("%Y-%m-%d")
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO run_log (ticker, date, rating, trade_side, trade_qty, duration_secs, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ticker, date, rating, trade_side, trade_qty, duration_secs, error),
            )
        status = "ERROR" if error else rating
        logger.info("Run logged: %s → %s (%.0fs)", ticker, status, duration_secs)

    def today_runs(self, date: Optional[str] = None) -> list[RunRecord]:
        """Get all runs for a given day.

        Args:
            date: Date string (YYYY-MM-DD). Defaults to today.

        Returns:
            List of RunRecord, ordered by creation time.
        """
        date = date or datetime.now().strftime("%Y-%m-%d")
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM run_log WHERE date = ? ORDER BY created_at",
                (date,),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def all_runs(self, limit: int = 100) -> list[RunRecord]:
        """Get recent runs across all days."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM run_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def clear_today(
        self, ticker: Optional[str] = None, date: Optional[str] = None,
    ) -> int:
        """Clear run records for re-analysis.

        Args:
            ticker: Clear only this ticker. None = clear all for the day.
            date: Date to clear. Defaults to today.

        Returns:
            Number of records deleted.
        """
        date = date or datetime.now().strftime("%Y-%m-%d")
        with self._conn() as conn:
            if ticker:
                cursor = conn.execute(
                    "DELETE FROM run_log WHERE ticker = ? AND date = ?",
                    (ticker, date),
                )
            else:
                cursor = conn.execute(
                    "DELETE FROM run_log WHERE date = ?", (date,),
                )
            deleted = cursor.rowcount
        if deleted:
            target = ticker or "all tickers"
            logger.info("Cleared %d run(s) for %s on %s", deleted, target, date)
        return deleted

    def run_stats(self, date: Optional[str] = None) -> dict:
        """Summary stats for a day's runs.

        Returns dict with: total, success, errors, tickers, duration_total.
        """
        runs = self.today_runs(date)
        success = [r for r in runs if not r.error]
        errors = [r for r in runs if r.error]
        return {
            "date": date or datetime.now().strftime("%Y-%m-%d"),
            "total": len(runs),
            "success": len(success),
            "errors": len(errors),
            "tickers": [r.ticker for r in runs],
            "ratings": {r.ticker: r.rating for r in success},
            "duration_total_secs": sum(r.duration_secs for r in runs),
        }

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            id=row["id"],
            ticker=row["ticker"],
            date=row["date"],
            rating=row["rating"],
            trade_side=row["trade_side"],
            trade_qty=row["trade_qty"],
            duration_secs=row["duration_secs"],
            error=row["error"],
            created_at=row["created_at"],
        )
