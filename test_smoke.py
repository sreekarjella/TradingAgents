"""
TradingAgents — India Market Smoke Test (Phase 1)
===================================================
Tests the India-adapted pipeline with RELIANCE.NS:
- NIFTY 50 benchmark instead of SPY
- India-centric news queries (RBI, FII/DII, etc.)
- Market context (SEBI, circuit limits, T+1, INR)
"""

import sys
import os

os.environ["PYTHONUNBUFFERED"] = "1"

from dotenv import load_dotenv

load_dotenv()

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.config_india import INDIA_CONFIG

# Merge defaults + India + Ollama overrides
config = {**DEFAULT_CONFIG, **INDIA_CONFIG}
config["llm_provider"] = "ollama"
config["deep_think_llm"] = "qwen3:32b"
config["quick_think_llm"] = "qwen3:14b"
config["max_debate_rounds"] = 1
config["max_risk_discuss_rounds"] = 1

ticker = "RELIANCE.NS"
trade_date = "2026-05-09"

print(f"\n{'='*60}", flush=True)
print(f"  INDIA SMOKE TEST (Phase 1)", flush=True)
print(f"  Ticker:    {ticker}", flush=True)
print(f"  Date:      {trade_date}", flush=True)
print(f"  Benchmark: {config['benchmark_name']} ({config['benchmark_ticker']})", flush=True)
print(f"  Analysts:  [market] only", flush=True)
print(f"  News:      India-centric queries", flush=True)
print(f"{'='*60}\n", flush=True)

ta = TradingAgentsGraph(
    selected_analysts=["market"],
    debug=True,
    config=config,
)

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
