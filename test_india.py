"""
TradingAgents — First Indian Market Test
=========================================
Phase 0 validation: Run full 12-agent pipeline on RELIANCE.NS
using Qwen3 local models via Ollama.
"""

from dotenv import load_dotenv

load_dotenv()

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# Configure for Indian markets + Ollama
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

# Initialize
ta = TradingAgentsGraph(debug=True, config=config)

# Run on RELIANCE.NS with today's date
ticker = "RELIANCE.NS"
trade_date = "2026-05-09"

print(f"\n{'='*60}")
print(f"  TradingAgents — Indian Market Test")
print(f"  Ticker: {ticker}")
print(f"  Date:   {trade_date}")
print(f"  Deep:   qwen3:32b  |  Quick: qwen3:14b")
print(f"{'='*60}\n")

_, decision = ta.propagate(ticker, trade_date)

print(f"\n{'='*60}")
print(f"  FINAL DECISION")
print(f"{'='*60}")
print(decision)
