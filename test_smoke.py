"""
TradingAgents — Quick Smoke Test (1 analyst only)
===================================================
Minimal test: Market Analyst only → Researchers → Trader → Risk → PM
Uses unbuffered output for real-time monitoring.
"""

import sys
import os

# Force unbuffered stdout
os.environ["PYTHONUNBUFFERED"] = "1"

from dotenv import load_dotenv

load_dotenv()

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "ollama"
config["deep_think_llm"] = "qwen3:32b"
config["quick_think_llm"] = "qwen3:14b"
config["max_debate_rounds"] = 1
config["max_risk_discuss_rounds"] = 1

config["data_vendors"] = {
    "core_stock_apis": "yfinance",
    "technical_indicators": "yfinance",
    "fundamental_data": "yfinance",
    "news_data": "yfinance",
}

# Only use market analyst for speed
ta = TradingAgentsGraph(
    selected_analysts=["market"],
    debug=True,
    config=config,
)

ticker = "RELIANCE.NS"
trade_date = "2026-05-09"

print(f"\n{'='*60}", flush=True)
print(f"  SMOKE TEST — {ticker} on {trade_date}", flush=True)
print(f"  Analysts: [market] only", flush=True)
print(f"  Models: qwen3:32b (deep) + qwen3:14b (quick)", flush=True)
print(f"{'='*60}\n", flush=True)

try:
    _, decision = ta.propagate(ticker, trade_date)
    print(f"\n{'='*60}", flush=True)
    print(f"  FINAL DECISION: {decision}", flush=True)
    print(f"{'='*60}", flush=True)
except Exception as e:
    print(f"\n❌ ERROR: {e}", flush=True)
    import traceback
    traceback.print_exc()
    sys.exit(1)
