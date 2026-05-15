"""Daily trading runner — orchestrates pre-screen → pipeline → executor → portfolio.

Usage::

    python -m tradingagents.trading.daily_runner                # pre-screen → top 5
    python -m tradingagents.trading.daily_runner --no-screen    # old behavior (first 5)
    python -m tradingagents.trading.daily_runner --dry-run      # analyze only
    python -m tradingagents.trading.daily_runner --candidates=7 # screen top 7
    python -m tradingagents.trading.daily_runner --max-positions=8

Or from code::

    from tradingagents.trading.daily_runner import run_daily
    results = run_daily(broker, graph)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .broker import BrokerInterface, Order
from .executor import TradeAction, execute_trade, resolve_trade
from .portfolio import daily_pnl_report, portfolio_report
from .pre_screener import NIFTY_50, ScreenResult, pre_screen
from .run_tracker import RunTracker

logger = logging.getLogger(__name__)

# ── Defaults ─────────────────────────────────────────────────────────────
DEFAULT_UNIVERSE = NIFTY_50
MAX_POSITIONS = 10       # Hard cap on portfolio positions
DEFAULT_CANDIDATES = 5   # How many new candidates the screener picks


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
    screen_results: list[ScreenResult] = field(default_factory=list)
    portfolio_summary: str = ""
    pnl_summary: str = ""
    total_duration_secs: float = 0.0


def run_single(
    ticker: str,
    broker: BrokerInterface,
    graph,
    trade_date: str,
    dry_run: bool = False,
    sizing: dict | None = None,
    guardrails: dict | None = None,
    tracker: RunTracker | None = None,
) -> RunResult:
    """Run pipeline + executor for a single ticker.

    Args:
        ticker: Stock ticker (e.g. ``RELIANCE.NS``).
        broker: Broker implementation.
        graph: TradingAgentsGraph instance.
        trade_date: Date string (YYYY-MM-DD).
        dry_run: If True, resolve trades but don't execute.
        sizing: Position sizing overrides from config.toml.
        guardrails: Trade guardrails from config.toml.
        tracker: RunTracker for duplicate detection. None = no check.

    Returns:
        RunResult with rating, action, and order details.
    """
    # ── Duplicate check ──────────────────────────────────────────────
    if tracker and tracker.was_analyzed_today(ticker, date=trade_date):
        logger.info("⚠️  SKIP %s — already analyzed today", ticker)
        return RunResult(
            ticker=ticker, rating="Duplicate",
            trade_action=TradeAction(
                ticker=ticker, rating="Duplicate", side=None, quantity=0,
                estimated_price=0, estimated_value=0,
                rationale="Already analyzed today — duplicate blocked.",
                skipped=True, skip_reason="Duplicate: already analyzed today",
            ),
            duration_secs=0.0,
        )

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
        trade = resolve_trade(
            ticker, rating, decision_text, broker,
            sizing_overrides=sizing, guardrails=guardrails,
        )

        # Execute (or dry run)
        order = execute_trade(trade, broker, dry_run=dry_run)

        duration = (datetime.now() - start).total_seconds()

        # Log successful run
        if tracker:
            tracker.log_run(
                ticker, rating=rating,
                trade_side=trade.side if not trade.skipped else None,
                trade_qty=trade.quantity if not trade.skipped else 0,
                duration_secs=duration,
            )

        return RunResult(
            ticker=ticker, rating=rating, trade_action=trade,
            order=order, duration_secs=duration,
        )

    except Exception as e:
        duration = (datetime.now() - start).total_seconds()
        logger.error("ERROR analyzing %s: %s", ticker, e, exc_info=True)

        # Log failed run (won't block re-analysis — only successes count)
        if tracker:
            tracker.log_run(ticker, error=str(e), duration_secs=duration)

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


def _count_active_positions(broker: BrokerInterface) -> int:
    """Return the number of currently held positions.

    Delegates to the broker's ``count_active_positions`` so paper/live
    backends can answer with a SQL ``COUNT(*)`` instead of fanning out
    N yfinance roundtrips through ``get_holdings()`` (each holding
    triggers a ``get_ltp`` price fetch). This function used to be called
    3+ times per ``run_daily`` — a 10-position holdings review meant
    30+ unnecessary HTTP calls just for bookkeeping.
    """
    return broker.count_active_positions()


def _available_buy_slots(broker: BrokerInterface, max_positions: int) -> int:
    """How many new stocks we can buy before hitting the cap."""
    return max(0, max_positions - _count_active_positions(broker))


def run_daily(
    broker: BrokerInterface,
    graph,
    universe: Optional[list[str]] = None,
    trade_date: Optional[str] = None,
    dry_run: bool = False,
    review_holdings: bool = True,
    max_positions: int = MAX_POSITIONS,
    num_candidates: int = DEFAULT_CANDIDATES,
    use_screener: bool = True,
    sizing: dict | None = None,
    guardrails: dict | None = None,
    screener_weights: dict | None = None,
    bullish_keywords: list[str] | None = None,
    bearish_keywords: list[str] | None = None,
    buy_bias: bool = True,
) -> DailyReport:
    """Run the full daily trading cycle with intelligent pre-screening.

    Steps:
        1. Pre-screen all 50 NIFTY stocks (fast, no LLM) → pick top N
        2. Review existing holdings → sell if Underweight/Sell
        3. Analyze new candidates (only if portfolio has room)
        4. Take daily snapshot
        5. Generate report

    Args:
        broker: Broker implementation (paper or live).
        graph: TradingAgentsGraph instance.
        universe: Full list of tickers to scan. Defaults to NIFTY 50.
        trade_date: Override date (YYYY-MM-DD). Defaults to today.
        dry_run: If True, resolve trades but don't execute.
        review_holdings: If True, re-analyze existing positions first.
        max_positions: Maximum portfolio positions (default 10).
        num_candidates: How many new tickers the screener picks (default 5).
        use_screener: If False, skip pre-screening (use first N of universe).

    Returns:
        DailyReport with all results, screen results, and portfolio summary.
    """
    trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")
    universe = universe or DEFAULT_UNIVERSE
    start = datetime.now()

    # ── Initialize run tracker for duplicate detection ───────────────
    tracker = RunTracker()

    report = DailyReport(date=trade_date)

    logger.info("=" * 60)
    logger.info("🐶 DAILY TRADING RUN — %s", trade_date)
    logger.info("=" * 60)
    logger.info("Mode: %s", "DRY RUN" if dry_run else "LIVE EXECUTION")
    logger.info("Max positions: %d | New candidates: %d", max_positions, num_candidates)
    logger.info("Universe: %d tickers | Screener: %s", len(universe),
                "ON (buy-biased)" if use_screener else "OFF")

    # ── Step 1: Review existing holdings ─────────────────────────────
    held_tickers: set[str] = set()
    if review_holdings:
        holdings = broker.get_holdings()
        held_tickers = {h.ticker for h in holdings}

        if held_tickers:
            logger.info("\n📋 Reviewing %d existing positions...", len(held_tickers))
            for ticker in held_tickers:
                result = run_single(
                    ticker, broker, graph, trade_date, dry_run,
                    sizing=sizing, guardrails=guardrails,
                    tracker=tracker,
                )
                report.results.append(result)

    # Re-check position count (sells during review may have freed slots)
    buy_slots = _available_buy_slots(broker, max_positions)
    logger.info("\n📊 Portfolio: %d positions, %d buy slots available",
                _count_active_positions(broker), buy_slots)

    if buy_slots <= 0:
        logger.info("Portfolio full (%d/%d positions) — skipping new candidates",
                     _count_active_positions(broker), max_positions)
    else:
        # ── Step 2: Pick candidates (screener or static) ─────────────
        # Only pick as many candidates as we have room for
        effective_candidates = min(num_candidates, buy_slots)

        if use_screener:
            logger.info("\n🔍 Pre-screening %d tickers to find top %d...",
                        len(universe), effective_candidates)
            screen_results = pre_screen(
                universe=universe,
                top_n=effective_candidates,
                trade_date=trade_date,
                exclude=held_tickers,
                buy_bias=buy_bias,
                weights=screener_weights,
                bullish_keywords=bullish_keywords,
                bearish_keywords=bearish_keywords,
            )
            report.screen_results = screen_results
            candidates = [r.ticker for r in screen_results]
        else:
            candidates = [t for t in universe if t not in held_tickers][:effective_candidates]

        # ── Step 3: Run pipeline on candidates ───────────────────────
        logger.info("\n🎯 Analyzing %d candidates: %s", len(candidates), ", ".join(candidates))
        for ticker in candidates:
            result = run_single(
                ticker, broker, graph, trade_date, dry_run,
                sizing=sizing, guardrails=guardrails,
                tracker=tracker,
            )
            report.results.append(result)

            # Re-check slots after each trade (a Buy consumes a slot)
            if not dry_run and result.order and result.order.side == "BUY" and result.order.status == "FILLED":
                remaining = _available_buy_slots(broker, max_positions)
                if remaining <= 0:
                    logger.info("Portfolio now full (%d positions) — stopping candidate scan", max_positions)
                    break

    # ── Step 4: Daily snapshot ───────────────────────────────────────
    from .paper_broker import PaperBroker
    if isinstance(broker, PaperBroker):
        broker.take_daily_snapshot()

    # ── Step 5: Generate reports ─────────────────────────────────────
    report.portfolio_summary = portfolio_report(broker)
    report.pnl_summary = daily_pnl_report(broker)
    report.total_duration_secs = (datetime.now() - start).total_seconds()

    _log_daily_summary(report)

    return report


def _log_daily_summary(report: DailyReport) -> None:
    """Print a nice summary to the log."""
    logger.info("\n" + "=" * 60)
    logger.info("📊 DAILY SUMMARY — %s", report.date)
    logger.info("=" * 60)

    # Pre-screen results
    if report.screen_results:
        logger.info("\n🔍 Pre-screen picks:")
        for i, sr in enumerate(report.screen_results, 1):
            reasons = ", ".join(sr.reasons) if sr.reasons else "baseline"
            sent = f" [sentiment: {sr.news_sentiment:+.1f}]" if sr.news_mentions > 0 else ""
            logger.info("  %d. %s — score %+.1f%s (%s)", i, sr.ticker, sr.total_score, sent, reasons)

    # Count by rating
    ratings: dict[str, int] = {}
    for r in report.results:
        ratings[r.rating] = ratings.get(r.rating, 0) + 1

    logger.info("\nRatings: %s", " | ".join(f"{k}: {v}" for k, v in sorted(ratings.items())))

    # Trades executed
    executed = [r for r in report.results if r.order and r.order.status == "FILLED"]
    skipped = [r for r in report.results if r.trade_action.skipped and r.rating != "Duplicate"]
    duplicates = [r for r in report.results if r.rating == "Duplicate"]
    errors = [r for r in report.results if r.error]

    logger.info("Executed: %d | Skipped: %d | Duplicates blocked: %d | Errors: %d",
                len(executed), len(skipped), len(duplicates), len(errors))

    for r in executed:
        logger.info(
            "  ✅ %s %s x%d @ ₹%.2f",
            r.order.side, r.order.ticker, r.order.quantity, r.order.price,
        )

    logger.info("\n%s", report.pnl_summary)
    logger.info("Total runtime: %.0f seconds (%.1f min)", report.total_duration_secs, report.total_duration_secs / 60)


# ── CLI entry point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    import sys

    from dotenv import load_dotenv
    load_dotenv()

    # Tell langchain-openai to skip its TCP-keepalive httpx-transport injection.
    # That injection silently disables HTTP_PROXY auto-detection AND emits a
    # multi-line warning on every run; we don't need its keepalive tweaks for
    # local Ollama and our own configure_network() handles proxy already.
    os.environ.setdefault("LANGCHAIN_OPENAI_TCP_KEEPALIVE", "0")

    from tradingagents.network import configure_network
    configure_network()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load unified config from config.toml
    from tradingagents.config_loader import load_config

    config_path = "config.toml"
    for arg in sys.argv[1:]:
        if arg.startswith("--config="):
            config_path = arg.split("=", 1)[1]

    cfg = load_config(config_path)

    # Import here to avoid circular deps at module level
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from . import create_broker

    # CLI flag overrides (take precedence over config.toml)
    dry_run = "--dry-run" in sys.argv
    use_screener = cfg.screener_enabled and "--no-screen" not in sys.argv
    num_candidates = cfg.screener_candidates
    max_positions = cfg.max_positions
    custom_tickers = None

    for arg in sys.argv[1:]:
        if arg.startswith("--tickers="):
            use_screener = False
            custom_tickers = arg.split("=", 1)[1].split(",")
        elif arg.startswith("--candidates="):
            num_candidates = int(arg.split("=")[1])
        elif arg.startswith("--max-positions="):
            max_positions = int(arg.split("=")[1])

    broker = create_broker(cfg.broker_config)
    graph = TradingAgentsGraph(config=cfg.pipeline_config)

    universe = custom_tickers if custom_tickers else cfg.universe

    print(f"\n🐶 Starting daily run — {cfg.trading_mode} mode")
    print(f"   Config: {cfg.source_path}")
    print(f"   LLM: {cfg.llm_provider} ({cfg.quick_think_model} / {cfg.deep_think_model})")
    print(f"   Screener: {'ON (scanning all {})'.format(len(universe)) if use_screener else 'OFF'}")
    print(f"   Max positions: {max_positions} | New candidates: {num_candidates}")
    print(f"   Capital: ₹{cfg.initial_capital:,.0f} | Mode: {'DRY RUN' if dry_run else 'LIVE EXECUTION'}")
    print()

    report = run_daily(
        broker, graph,
        universe=universe,
        dry_run=dry_run,
        use_screener=use_screener,
        num_candidates=num_candidates,
        max_positions=max_positions,
        sizing=cfg.sizing,
        guardrails=cfg.guardrails,
        screener_weights=cfg.screener_weights,
        bullish_keywords=cfg.bullish_keywords,
        bearish_keywords=cfg.bearish_keywords,
        buy_bias=cfg.screener_buy_bias,
    )

    print("\n" + report.portfolio_summary)
