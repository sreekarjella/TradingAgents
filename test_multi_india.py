"""
TradingAgents — Multi-Stock India Test (Phase 1)
==================================================
Tests the India-adapted pipeline against a basket of popular NSE stocks.
Runs sequentially with 1-analyst config for speed.
"""

import sys
import os
import json
from datetime import datetime

os.environ["PYTHONUNBUFFERED"] = "1"

from dotenv import load_dotenv

load_dotenv()

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.config_india import INDIA_CONFIG

# NIFTY 50 blue-chips for testing
INDIA_STOCKS = [
    "RELIANCE.NS",
    "TCS.NS",
    "INFY.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "HINDUNILVR.NS",
    "ITC.NS",
    "BHARTIARTL.NS",
    "SBIN.NS",
    "LT.NS",
]

# Merge defaults + India + Ollama
config = {**DEFAULT_CONFIG, **INDIA_CONFIG}
config["llm_provider"] = "ollama"
config["deep_think_llm"] = "qwen3:32b"
config["quick_think_llm"] = "qwen3:14b"
config["max_debate_rounds"] = 1
config["max_risk_discuss_rounds"] = 1

trade_date = "2026-05-09"
results = []

print(f"\n{'='*60}", flush=True)
print(f"  MULTI-STOCK INDIA TEST (Phase 1)", flush=True)
print(f"  Stocks: {len(INDIA_STOCKS)}", flush=True)
print(f"  Date:   {trade_date}", flush=True)
print(f"  Config: 1 analyst (market), 1 debate round", flush=True)
print(f"{'='*60}\n", flush=True)

ta = TradingAgentsGraph(
    selected_analysts=["market"],
    debug=False,  # quieter for batch runs
    config=config,
)

for i, ticker in enumerate(INDIA_STOCKS, 1):
    print(f"\n[{i}/{len(INDIA_STOCKS)}] Analyzing {ticker}...", flush=True)
    start = datetime.now()

    try:
        _, decision = ta.propagate(ticker, trade_date)
        elapsed = (datetime.now() - start).total_seconds()

        # Extract the action word from the decision
        action = "UNKNOWN"
        for word in ["Buy", "Sell", "Hold", "Overweight", "Underweight"]:
            if word.lower() in decision.lower():
                action = word
                break

        results.append({
            "ticker": ticker,
            "decision": action,
            "elapsed_sec": round(elapsed),
            "full_decision": decision[:200],
        })
        print(f"  → {action} ({elapsed:.0f}s)", flush=True)

    except Exception as e:
        elapsed = (datetime.now() - start).total_seconds()
        results.append({
            "ticker": ticker,
            "decision": "ERROR",
            "elapsed_sec": round(elapsed),
            "full_decision": str(e)[:200],
        })
        print(f"  → ERROR: {e}", flush=True)

# Summary
print(f"\n{'='*60}", flush=True)
print(f"  RESULTS SUMMARY", flush=True)
print(f"{'='*60}", flush=True)
print(f"{'Ticker':<16} {'Decision':<12} {'Time (s)':<10}", flush=True)
print(f"{'-'*38}", flush=True)
for r in results:
    print(f"{r['ticker']:<16} {r['decision']:<12} {r['elapsed_sec']:<10}", flush=True)

# Save results
output_file = f"/tmp/india_multi_{trade_date}.json"
with open(output_file, "w") as f:
    json.dump(results, f, indent=2)
print(f"\nResults saved to {output_file}", flush=True)
