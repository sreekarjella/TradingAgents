"""Daily trading runner — orchestrates pipeline → executor → portfolio.

Usage:
    python -m tradingagents.trading.daily_runner

Or from code:
    from tradingagents.trading.daily_runner import run_daily
    results = run_daily(config)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from tradingagents.agents.utils.rating import parse_rating

from .broker import BrokerInterface, Order
from .executor import TradeAction, execute_trade, resolve_trade
from .portfolio import daily_pnl_report, portfolio_report

logger = logging.getLogger(__name__)

# Default NIFTY 50 blue-chips for scanning
DEFAULT_UNIVERSE = [
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "BAJFINANCE.NS", "MARUTI.NS", "TITAN.NS",
    "SUNPHARMA.NS", "TATAMOTORS.NS", "ONGC.NS", "NTPC.NS", "POWERGRID.NS",
]


@dataclass
class RunResult:
    """Result of running the pipeline for a single ticker."""

    ticker: str
    rating: str
    trade_action: TradeAction
    order: Optional[Order] = None
    error: Optional[str] = None
    duration_secs: float = 0.0


@dataclass
class DailyReport:
    """Summary of a full daily run."""

    date: str
    results: list[RunResult] = field(default_factory=list)
    portfolio_summary: str = ""
    pnl_summary: str = ""
    total_duration_secs: float = 0.0


def run_single(
    ticker: str,
    broker: BrokerInterface,
    graph,
    trade_date: str,
    dry_run: bool = False,
) -> RunResult:
    """Run pipeline + executor for a single ticker.

    Args:
        ticker: Stock ticker (e.g. ``RELIANCE.NS``).
        broker: Broker implementation.
        graph: TradingAgentsGraph instance.
        trade_date: Date string (YYYY-MM-DD).
        dry_run: If True, resolve trades but don't execute.

    Returns:
        RunResult with rating, action, and order details.
    """
    start = datetime.now()
    logger.info("━" * 50)
    logger.info("Analyzing %s...", ticker)

    try:
        # Run the full agent pipeline
        final_state, signal = graph.propagate(ticker, trade_date)
        rating = signal  # Already parsed by SignalProcessor
        decision_text = final_state["final_trade_decision"]

        logger.info("%s → Rating: %s", ticker, rating)

        # Resolve to concrete trade
        trade = resolve_trade(ticker, rating, decision_text, broker)

        # Execute (or dry run)
        order = execute_trade(trade, broker, dry_run=dry_run)

        duration = (datetime.now() - start).total_seconds()
        return RunResult(
            ticker=ticker, rating=rating, trade_action=trade,
            order=order, duration_secs=duration,
        )

    except Exception as e:
        duration = (datetime.now() - start).total_seconds()
        logger.error("ERROR analyzing %s: %s", ticker, e, exc_info=True)
        return RunResult(
            ticker=ticker, rating="Error", error=str(e),
            trade_action=TradeAction(
                ticker=ticker, rating="Error", side=None, quantity=0,
                estimated_price=0, estimated_value=0,
                rationale=f"Pipeline error: {e}",
                skipped=True, skip_reason=str(e),
            ),
            duration_secs=duration,
        )


def run_daily(
    broker: BrokerInterface,
    graph,
    universe: Optional[list[str]] = None,
    trade_date: Optional[str] = None,
    dry_run: bool = False,
    review_holdings: bool = True,
) -> DailyReport:
    """Run the full daily trading cycle.

    Steps:
        1. Review existing holdings (re-analyze, sell if needed)
        2. Scan universe for new opportunities
        3. Take daily snapshot
        4. Generate report

    Args:
        broker: Broker implementation (paper or live).
        graph: TradingAgentsGraph instance.
        universe: List of tickers to scan. Defaults to top NIFTY 50.
        trade_date: Override date (YYYY-MM-DD). Defaults to today.
        dry_run: If True, resolve trades but don't execute.
        review_holdings: If True, re-analyze existing positions first.

    Returns:
        DailyReport with all results and portfolio summary.
    """
    trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")
    universe = universe or DEFAULT_UNIVERSE
    start = datetime.now()

    report = DailyReport(date=trade_date)

    logger.info("=" * 60)
    logger.info("🐶 DAILY TRADING RUN — %s", trade_date)
    logger.info("=" * 60)
    logger.info("Mode: %s", "DRY RUN" if dry_run else "LIVE EXECUTION")
    logger.info("Universe: %d tickers", len(universe))

    # Step 1: Review existing holdings
    if review_holdings:
        holdings = broker.get_holdings()
        held_tickers = {h.ticker for h in holdings}

        if held_tickers:
            logger.info("\n📋 Reviewing %d existing positions...", len(held_tickers))
            for ticker in held_tickers:
                result = run_single(ticker, broker, graph, trade_date, dry_run)
                report.results.append(result)

            # Remove held tickers from scan universe (already analyzed)
            universe = [t for t in universe if t not in held_tickers]

    # Step 2: Scan universe for new opportunities
    logger.info("\n🔍 Scanning %d tickers for opportunities...", len(universe))
    for ticker in universe:
        result = run_single(ticker, broker, graph, trade_date, dry_run)
        report.results.append(result)

    # Step 3: Daily snapshot
    from .paper_broker import PaperBroker
    if isinstance(broker, PaperBroker):
        broker.take_daily_snapshot()

    # Step 4: Generate reports
    report.portfolio_summary = portfolio_report(broker)
    report.pnl_summary = daily_pnl_report(broker)
    report.total_duration_secs = (datetime.now() - start).total_seconds()

    # Log summary
    _log_daily_summary(report)

    return report


def _log_daily_summary(report: DailyReport) -> None:
    """Print a nice summary to the log."""
    logger.info("\n" + "=" * 60)
    logger.info("📊 DAILY SUMMARY — %s", report.date)
    logger.info("=" * 60)

    # Count by rating
    ratings = {}
    for r in report.results:
        ratings[r.rating] = ratings.get(r.rating, 0) + 1

    logger.info("Ratings: %s", " | ".join(f"{k}: {v}" for k, v in sorted(ratings.items())))

    # Trades executed
    executed = [r for r in report.results if r.order and r.order.status == "FILLED"]
    skipped = [r for r in report.results if r.trade_action.skipped]
    errors = [r for r in report.results if r.error]

    logger.info("Executed: %d | Skipped: %d | Errors: %d", len(executed), len(skipped), len(errors))

    for r in executed:
        logger.info(
            "  ✅ %s %s x%d @ ₹%.2f",
            r.order.side, r.order.ticker, r.order.quantity, r.order.price,
        )

    logger.info("\n%s", report.pnl_summary)
    logger.info("Total runtime: %.0f seconds (%.1f min)", report.total_duration_secs, report.total_duration_secs / 60)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    from dotenv import load_dotenv
    load_dotenv()

    from tradingagents.network import configure_network
    configure_network()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Import here to avoid circular deps at module level
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    # Load config
    try:
        from tradingagents.config_india import INDIA_CONFIG as config
    except ImportError:
        from tradingagents.default_config import DEFAULT_CONFIG as config

    from . import create_broker

    # Parse CLI args
    dry_run = "--dry-run" in sys.argv
    mode = "paper"  # Always paper for daily runner
    universe_size = 5  # Start small

    # Pick universe
    universe = DEFAULT_UNIVERSE[:universe_size]

    # Override from CLI
    for arg in sys.argv[1:]:
        if arg.startswith("--tickers="):
            universe = arg.split("=")[1].split(",")
        elif arg.startswith("--mode="):
            mode = arg.split("=")[1]
        elif arg.startswith("--universe="):
            universe_size = int(arg.split("=")[1])
            universe = DEFAULT_UNIVERSE[:universe_size]

    broker = create_broker({"trading_mode": mode})
    graph = TradingAgentsGraph(config=config)

    print(f"\n🐶 Starting daily run — {len(universe)} tickers, {mode} mode")
    print(f"   Tickers: {', '.join(universe)}")
    print(f"   {'DRY RUN' if dry_run else 'LIVE EXECUTION'}")
    print()

    report = run_daily(broker, graph, universe=universe, dry_run=dry_run)

    print("\n" + report.portfolio_summary)
