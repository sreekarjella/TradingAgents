"""Full pipeline test: Agent analysis → decision → paper trade.

Runs the complete TradingAgents pipeline for a single ticker,
then auto-executes the decision as a paper trade.
"""

import logging
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

# Prevent langchain-openai from injecting its own httpx transport
# which overrides our proxy=None client for Ollama.
import os
os.environ["LANGCHAIN_OPENAI_TCP_KEEPALIVE"] = "0"

# Auto-detect network (Walmart proxy vs home direct)
from tradingagents.network import configure_network

network = configure_network()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline_test")

# Suppress noisy loggers
for name in ("httpx", "httpcore", "urllib3", "yfinance", "peewee"):
    logging.getLogger(name).setLevel(logging.WARNING)


def main():
    ticker = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE.NS"
    trade_date = datetime.now().strftime("%Y-%m-%d")
    dry_run = "--dry-run" in sys.argv

    logger.info("=" * 60)
    logger.info("🐶 FULL PIPELINE TEST")
    logger.info("=" * 60)
    logger.info("Ticker:    %s", ticker)
    logger.info("Date:      %s", trade_date)
    logger.info("Network:   %s", network)
    logger.info("Mode:      %s", "DRY RUN" if dry_run else "PAPER TRADING")
    logger.info("=" * 60)

    # ── Step 1: Build config ──────────────────────────────────
    logger.info("\n📋 Step 1: Loading India config + Ollama...")
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.config_india import INDIA_CONFIG

    config = {
        **DEFAULT_CONFIG,
        **INDIA_CONFIG,
        "llm_provider": "ollama",
        "deep_think_llm": "qwen3:32b",
        "quick_think_llm": "qwen3:14b",
        "backend_url": None,  # Ollama client defaults to http://localhost:11434/v1
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
    }

    # ── Step 2: Create broker ─────────────────────────────────
    logger.info("\n💰 Step 2: Creating paper broker (₹10L capital)...")
    from tradingagents.trading import create_broker

    broker = create_broker({
        "trading_mode": "paper",
        "initial_capital": 10_00_000.0,
    })
    logger.info("Cash available: ₹%s", f"{broker.get_cash():,.0f}")

    # ── Step 3: Run agent pipeline ────────────────────────────
    logger.info("\n🤖 Step 3: Running TradingAgents pipeline...")
    logger.info("This will take ~15-25 minutes (4 analysts + debate + risk + PM)")
    logger.info("Go grab a chai ☕")

    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = TradingAgentsGraph(config=config)

    start = time.time()
    final_state, signal = graph.propagate(ticker, trade_date)
    elapsed = time.time() - start

    logger.info("\n⏱️  Pipeline completed in %.1f minutes", elapsed / 60)
    logger.info("Signal: %s", signal)

    # ── Step 4: Show decision ─────────────────────────────────
    decision = final_state["final_trade_decision"]
    logger.info("\n📊 Step 4: Portfolio Manager Decision")
    logger.info("─" * 40)
    print(decision)
    print("─" * 40)

    # ── Step 5: Execute trade ─────────────────────────────────
    logger.info("\n💹 Step 5: Executing trade...")
    from tradingagents.trading import resolve_trade, execute_trade

    trade = resolve_trade(ticker, signal, decision, broker)

    if trade.skipped:
        logger.info("SKIPPED: %s", trade.skip_reason)
    else:
        logger.info("Resolved: %s %s x%d @ ~₹%.2f = ~₹%.0f",
                     trade.side, trade.ticker, trade.quantity,
                     trade.estimated_price, trade.estimated_value)

        if dry_run:
            logger.info("DRY RUN — no")
        else:
            order = execute_trade(trade, broker)
            if order:
                logger.info("✅ EXECUTED: %s x%d @ ₹%.2f [%s]",
                             order.side, order.quantity, order.price, order.status)
                if order.pnl is not None:
                    logger.info("   Realized P&L: ₹%.2f", order.pnl)

    # ── Step 6: Portfolio report ──────────────────────────────
    logger.info("\n📈 Step 6: Portfolio Report")
    from tradingagents.trading import portfolio_report

    print(portfolio_report(broker))

    # ── Summary ───────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("🐶 PIPELINE COMPLETE")
    logger.info("   Ticker: %s → %s", ticker, signal)
    logger.info("   Runtime: %.1f min", elapsed / 60)
    logger.info("   Portfolio: ₹%s", f"{broker.get_portfolio().total_value:,.0f}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
