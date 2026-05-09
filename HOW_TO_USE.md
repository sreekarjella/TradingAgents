# 🐶 TradingAgents — How to Use

> **Multi-Agent AI Trading Framework** — 4 analysts debate, a risk team challenges, and a portfolio manager decides.  
> Works with Indian stocks (NSE/BSE), US stocks, and any ticker yfinance supports.
>
> 📖 **New here?** Read [HOW_IT_WORKS.md](HOW_IT_WORKS.md) first — a plain-English guide with zero jargon.

---

## Table of Contents

1. [Quick Start](#1-quick-start)
2. [Installation](#2-installation)
3. [Configuration](#3-configuration)
4. [Running the Pipeline](#4-running-the-pipeline)
5. [How It Works — Architecture](#5-how-it-works--architecture)
6. [LLM Providers](#6-llm-providers)
7. [Data Sources](#7-data-sources)
8. [Paper Trading](#8-paper-trading)
9. [Live Trading (Angel One)](#9-live-trading-angel-one)
10. [Daily Runner (Multi-Ticker)](#10-daily-runner-multi-ticker)
11. [Pre-Screener (Stock Selection)](#11-pre-screener-stock-selection)
12. [Interactive CLI](#12-interactive-cli)
13. [Memory & Learning](#13-memory--learning)
14. [All Config Options](#14-all-config-options)
15. [Troubleshooting](#15-troubleshooting)

---

## 1. Quick Start

**Fastest path from zero to a trading decision:**

```bash
# 1. Clone and install
git clone <repo-url> && cd TradingAgents
uv venv && source .venv/bin/activate
uv pip install -e .

# 2. Set up your LLM (pick ONE)
# Option A: Local Ollama (free, private, no API key)
ollama pull qwen3:14b

# Option B: Cloud API (faster, costs money)
echo "OPENAI_API_KEY=sk-..." > .env

# 3. Run for a single stock
python run_pipeline.py RELIANCE.NS       # Indian stock
python run_pipeline.py AAPL              # US stock
python run_pipeline.py RELIANCE.NS --dry-run  # Preview without trading
```

**That's it.** The pipeline will:
- Fetch market data, news, fundamentals
- Run 4 AI analysts (market, social, news, fundamentals)
- Conduct a bull vs bear debate
- Assess risk through 3 risk perspectives
- Produce a final **Buy / Overweight / Hold / Underweight / Sell** decision
- Execute a paper trade automatically

---

## 2. Installation

### Prerequisites

| Requirement | Version | Why |
|---|---|---|
| Python | ≥ 3.10 | LangGraph, type hints |
| uv | any | Fast package manager |
| Ollama (optional) | ≥ 0.9 | Local LLM inference |

### Steps

```bash
# Clone
git clone <repo-url>
cd TradingAgents

# Create virtual environment (DO NOT use system python)
uv venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# Install all dependencies
uv pip install -e .

# Verify
python -c "from tradingagents.graph.trading_graph import TradingAgentsGraph; print('✅ Ready!')"
```

### Ollama Setup (for local LLM)

```bash
# Install Ollama
brew install ollama        # macOS
# curl -fsSL https://ollama.com/install.sh | sh  # Linux

# Pull models (pick based on your RAM)
ollama pull qwen3:8b       # 8GB RAM minimum (fast, decent)
ollama pull qwen     # 16GB RAM (good balance — recommended)
ollama pull qwen3:32b      # 32GB RAM (best quality, slower)

# Verify
ollama list
```

---

## 3. Configuration

### Environment Variables (`.env`)

Copy `.env.example` and fill in your provider's key:

```bash
cp .env.example .env
```

```ini
# Pick ONE provider and set its key:
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=AI...
XAI_API_KEY=xai-...
DEEPSEEK_API_KEY=sk-...

# For Azure OpenAI (see .env.enterprise.example):
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/

# Angel One (for live trading only):
ANGEL_API_KEY=...
ANGEL_CLIENT_ID=...
ANGEL_PASSWORD=...
ANGEL_TOTP_SECRET=...
```

> **Ollama needs no API key** — it runs locally on your machine.

### Config Dict

All behavior is controlled by a Python dict passed to `TradingAgentsGraph`:

```python
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.config_india import INDIA_CONFIG

# Start with defaults, override what you need
config = {
    **DEFAULT_CONFIG,
    **INDIA_CONFIG,           # Add India-specific settings
    "llm_provider": "ollama",
    "deep_think_llm": "qwen3:32b",
    "quick_think_llm": "qwen3:14b",
    "max_debate_rounds": 1,
}
```

---

## 4. Running the Pipeline

### Method 1: `run_pipeline.py` (Recommended for first run)

Single-ticker analysis with auto paper trading:

```bash
# Basic usage
python run_pipeline.py RELIANCE.NS

# Dry run (analyze only, don't trade)
python run_pipeline.py TCS.NS --dry-run

# US stock
python run_pipeline.py AAPL
```

**What it does:**
1. Loads India config + Ollama
2. Creates paper broker (₹10L capital)
3. Runs full agent pipeline (~15–30 min with local LLM)
4. Shows Portfolio Manager's decision
5. Executes paper trade
6. Prints portfolio report

### Method 2: Python API (for custom scripts)

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"
config["deep_think_llm"] = "gpt-5.4-mini"
config["quick_think_llm"] = "gpt-5.4-mini"

ta = TradingAgentsGraph(config=config)

# Analyze a stock
final_state, signal = ta.propagate("NVDA", "2024-05-10")

print(f"Decision: {signal}")  # Buy / Overweight / Hold / Underweight / Sell
print(final_state["final_trade_decision"])  # Full markdown report
```

### Method 3: Interactive CLI

```bash
tradingagents          # Launches interactive TUI
# or
python -m cli.main
```

The CLI walks you through provider selection, model choice, ticker input, and
displays a live dashboard as agents work.

---

## 5. How It Works — Architecture

```
                    ┌─────────────────────┐
                    │   You provide a     │
                    │   ticker + date     │
                    └────────┬────────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
        ┌─────▼────┐  ┌─────▼────┐  ┌──────▼─────┐  ┌────────────┐
        │  Market   │  │  Social  │  │   News     │  │ Fundament- │
        │  Analyst  │  │  Analyst │  │  Analyst   │  │ als Analyst│
        └─────┬────┘  └─────┬────┘  └──────┬─────┘  └─────┬──────┘
              │              │              │              │
              └──────────────┼──────────────┘              │
                             │ Reports                     │
                    ┌────────▼────────┐                    │
                    │ Research Manager │◄───────────────────┘
                    │ (Bull vs Bear   │
                    │  Debate)        │
                    └────────┬────────┘
                             │ Investment Plan
                    ┌────────▼────────┐
                    │     Trader      │
                    │ (Entry, Exit,   │
                    │  Position Size) │
                    └────────┬────────┘
                             │ Trade Proposal
              ┌──────────────┼──────────────┐
              │              │              │
        ┌─────▼─────┐ ┌─────▼─────┐ ┌──────▼──────┐
        │Aggressive │ │  Neutral  │ │Conservative │
        │  Risk     │ │   Risk    │ │    Risk     │
        │  Analyst  │ │  Analyst  │ │   Analyst   │
        └─────┬─────┘ └─────┬─────┘ └──────┬──────┘
              └──────────────┼──────────────┘
                             │ Risk Assessment
                    ┌────────▼────────┐
                    │   Portfolio     │
                    │    Manager      │
                    │ (Final Decision)│
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Trade Executor │
                    │ (Paper / Live)  │
                    └─────────────────┘
```

### The 4 Analysts

| Analyst | Data Sources | What It Does |
|---|---|---|
| **Market** | OHLCV prices, technical indicators | Trend, momentum, support/resistance |
| **Social** | News sentiment | Social media sentiment, buzz |
| **News** | RSS feeds, news APIs | Breaking news, macro events |
| **Fundamentals** | Balance sheet, income, cashflow | Valuation, debt, profitability |

### The 5-Tier Rating Scale

| Rating | Meaning | Trade Action |
|---|---|---|
| **Buy** | Strong conviction, load up | BUY 5% of portfolio |
| **Overweight** | Positive, gradually increase | BUY 3% of portfolio |
| **Hold** | Neutral, wait for clarity | No action |
| **Underweight** | Concerning, reduce exposure | SELL 50% of position |
| **Sell** | Exit now | SELL 100% of position |

### Select Specific Analysts

You don't have to run all 4 analysts — pick the ones you want:

```python
ta = TradingAgentsGraph(
    selected_analysts=["market", "fundamentals"],  # Skip social + news
    config=config,
)
```

Options: `"market"`, `"social"`, `"news"`, `"fundamentals"`

---

## 6. LLM Providers

### Supported Providers

| Provider | Config Value | Models | API Key Env Var |
|---|---|---|---|
| **Ollama** | `"ollama"` | Any local model | None needed |
| **OpenAI** | `"openai"` | GPT-5.4, GPT-4.1, etc. | `OPENAI_API_KEY` |
| **Anthropic** | `"anthropic"` | Claude Opus/Sonnet/Haiku | `ANTHROPIC_API_KEY` |
| **Google** | `"google"` | Gemini 2.5/3 Pro/Flash | `GOOGLE_API_KEY` |
| **xAI** | `"xai"` | Grok 4/4.1 | `XAI_API_KEY` |
| **DeepSeek** | `"deepseek"` | V3/V4 | `DEEPSEEK_API_KEY` |
| **Qwen** | `"qwen"` | Qwen 3/3.5 | `DASHSCOPE_API_KEY` |
| **OpenRouter** | `"openrouter"` | Any model via router | `OPENROUTER_API_KEY` |
| **Azure OpenAI** | `"azure"` | Deployed models | `AZURE_OPENAI_API_KEY` |

### Two LLM Roles

The framework uses **two** LLMs:

| Role | Config Key | Used For |
|---|---|---|
| **Quick Think** | `quick_think_llm` | Analysts, tool calls, risk debate, signal parsing |
| **Deep Think** | `deep_think_llm` | Research Manager debate, Portfolio Manager decision |

```python
config = {
    "llm_provider": "ollama",
    "quick_think_llm": "qwen3:14b",   # Faster, lighter
    "deep_think_llm": "qwen3:32b",    # Slower, smarter
}
```

### Ollama Model Recommendations

| Model | RAM | Speed | Quality | Best For |
|---|---|---|---|---|
| `qwen3:8b` | 8 GB | ⚡ Fast | ★★★ | Quick tests, low-end hardware |
| `qwen3:14b` | 16 GB | 🔄 Medium | ★★★★ | Daily use (recommended quick) |
| `qwen3:32b` | 32 GB | 🐢 Slow | ★★★★★ | Deep analysis (recommended deep) |

### Mixing Providers

Both models must use the **same provider**. You can't mix Ollama + OpenAI in one run.

---

## 7. Data Sources

### Vendor Configuration

```python
config["data_vendors"] = {
    "core_stock_apis": "yfinance",       # OHLCV price data
    "technical_indicators": "yfinance",  # RSI, MACD, Bollinger, etc.
    "fundamental_data": "yfinance",      # Balance sheet, income, cashflow
    "news_data": "india_rss,yfinance",   # Comma-separated = fallback chain
}
```

| Vendor | API Key Needed | Supports |
|---|---|---|
| `yfinance` | No | Global stocks, ETFs, indices |
| `alpha_vantage` | Yes (`ALPHA_VANTAGE_API_KEY`) | US-focused, rate-limited |
| `india_rss` | No | India news (ET, Moneycontrol, LiveMint) |

### Fallback Chains

Use comma-separated values for automatic fallback:

```python
"news_data": "india_rss,yfinance"
# Tries india_rss first → falls back to yfinance if RSS fails
```

### Tool-Level Overrides

Override a specific tool without changing the whole category:

```python
config["tool_vendors"] = {
    "get_stock_data": "alpha_vantage",  # Only this tool uses Alpha Vantage
}
```

---

## 8. Paper Trading

Paper trading simulates real trades with virtual money using real market prices. All data persists in a local SQLite database.

### Setup

```python
from tradingagents.trading import create_broker

broker = create_broker({
    "trading_mode": "paper",
    "initial_capital": 10_00_000.0,          # ₹10 Lakh (default)
    "paper_db_path": "data/paper_portfolio.db",  # SQLite file
})
```

### Position Sizing & Guardrails

The trade executor applies automatic guardrails:

| Rule | Value | Purpose |
|---|---|---|
| Buy allocation | 5% of portfolio | Diversification |
| Overweight allocation | 3% of portfolio | Gradual increase |
| Max per stock | 10% of portfolio | Concentration limit |
| Min trade | ₹500 | Avoid noise |
| Max trade | ₹1,00,000 | Safety cap |
| Underweight | Sell 50% of position | Gradual exit |
| Sell | Sell 100% of position | Full exit |

### Querying Portfolio State

```python
# Current holdings
holdings = broker.get_holdings()
for h in holdings:
    print(f"{h.ticker}: {h.quantity} @ ₹{h.avg_price:.2f}")

# Full portfolio snapshot
portfolio = broker.get_portfolio()
print(f"Cash: ₹{portfolio.cash:,.2f}")
print(f"Total: ₹{portfolio.total_value:,.2f}")

# Order history
orders = broker.get_order_history()

# Markdown report
from tradingagents.trading import portfolio_report
print(portfolio_report(broker))
```

---

## 9. Live Trading (Angel One)

> ⚠️ **Live trading executes real orders with real money.** Use at your own risk. Start with paper trading to validate your strategy.

### Prerequisites

1. An [Angel One](https://www.angelone.in/) trading account
2. SmartAPI access enabled (free at [smartapi.angelone.in](https://smartapi.angelone.in/))
3. API key, client ID, password, and TOTP secret

### Setup

Add credentials to `.env`:

```ini
ANGEL_API_KEY=your_api_key
ANGEL_CLIENT_ID=your_client_id
ANGEL_PASSWORD=your_password
ANGEL_TOTP_SECRET=your_base32_totp_secret
```

```python
from tradingagents.trading import create_broker

broker = create_broker({
    "trading_mode": "live",
    "angel_api_key": os.environ["ANGEL_API_KEY"],
    "angel_client_id": os.environ["ANGEL_CLIENT_ID"],
    "angel_password": os.environ["ANGEL_PASSWORD"],
    "angel_totp_secret": os.environ["ANGEL_TOTP_SECRET"],
})
```

### Paper → Live: One Config Flip

The broker interface is identical for paper and live. Switch by changing one value:

```python
# Paper (testing)
broker = create_broker({"trading_mode": "paper"})

# Live (real money)
broker = create_broker({"trading_mode": "live"})
```

All other code (`resolve_trade`, `execute_trade`, `portfolio_report`) works unchanged.

---

## 10. Daily Runner (Multi-Ticker)

The daily runner is the **main automation loop**: it pre-screens 50 stocks,
picks the most promising candidates, reviews existing holdings, runs the full
agent pipeline, and executes trades.

### Command Line

```bash
# Default: pre-screen all 50 NIFTY stocks, pick top 5, run pipeline
python -m tradingagents.trading.daily_runner

# Custom candidate count
python -m tradingagents.trading.daily_runner --candidates=7

# Cap portfolio at 8 positions
python -m tradingagents.trading.daily_runner --max-positions=8

# Skip screener, use specific tickers
python -m tradingagents.trading.daily_runner --tickers=RELIANCE.NS,TCS.NS,INFY.NS

# Skip screener, use first N from universe (old behavior)
python -m tradingagents.trading.daily_runner --no-screen

# Dry run (analyze only, no trades)
python -m tradingagents.trading.daily_runner --dry-run
```

### CLI Flags

| Flag | Default | Description |
|---|---|---|
| `--candidates=N` | 5 | How many new candidates the screener picks |
| `--max-positions=N` | 10 | Hard cap on portfolio positions |
| `--no-screen` | off | Skip pre-screener, use first N of universe |
| `--tickers=X,Y,Z` | — | Explicit tickers (implies `--no-screen`) |
| `--dry-run` | off | Analyze only, don’t execute trades |
| `--mode=paper\|live` | paper | Broker mode |

### Python API

```python
from tradingagents.trading.daily_runner import run_daily
from tradingagents.trading import create_broker
from tradingagents.graph.trading_graph import TradingAgentsGraph

broker = create_broker({"trading_mode": "paper"})
graph = TradingAgentsGraph(config=config)

report = run_daily(
    broker=broker,
    graph=graph,
    dry_run=False,
    review_holdings=True,
    use_screener=True,       # Enable pre-screener (default)
    num_candidates=5,        # Top 5 from screener
    max_positions=10,        # Portfolio cap
)

print(report.portfolio_summary)
```

### Daily Workflow

```
┌────────────────────────────────────────────────────────────┐
│  Step 1: PRE-SCREENER (~20 seconds, zero LLM)          │
│  Scan 50 NIFTY stocks → rank by buy opportunity score   │
│  Volume spikes + momentum + news sentiment + breakouts  │
└──────────────────────────┬─────────────────────────────────┘
                          │ Top 5 candidates
┌──────────────────────────┴─────────────────────────────────┐
│  Step 2: REVIEW HOLDINGS (~15 min per held stock)       │
│  Re-analyze each position → sell if Underweight/Sell    │
│  Frees up buy slots for new candidates                  │
└──────────────────────────┬─────────────────────────────────┘
                          │ Buy slots available?
┌──────────────────────────┴─────────────────────────────────┐
│  Step 3: ANALYZE CANDIDATES (~15 min per stock)         │
│  Full 12-agent pipeline → Buy/Overweight/Hold/Sell      │
│  Stops when portfolio is full (max_positions reached)    │
└──────────────────────────┬─────────────────────────────────┘
                          │
┌──────────────────────────┴─────────────────────────────────┐
│  Step 4: SNAPSHOT + REPORT                              │
│  Record portfolio state in SQLite, generate P&L report  │
└────────────────────────────────────────────────────────────┘
```

### Portfolio Position Cap

The system enforces a maximum number of positions (default 10):

```
Day 1:  0 held + 5 screened → analyze 5 → buy 3        → 3 positions
Day 2:  3 held + 5 screened → review 3 + analyze 5     → 6 positions
Day 3:  6 held + 5 screened → review 6 + analyze 4     → 9 positions
Day 4:  9 held + 5 screened → review 9 + analyze 1     → 10 positions (FULL)
Day 5: 10 held              → review 10 only            → sells 2 → 8 positions
        8 held + 5 screened → analyze 2 (only 2 slots) → 10 positions
```

---

## 11. Pre-Screener (Stock Selection)

The pre-screener is a fast, **zero-LLM** heuristic ranker that decides which
stocks deserve the expensive 15-minute agent pipeline.

### Why It Exists

The pipeline costs ~15 minutes per stock (with local LLMs). Scanning all 50
NIFTY stocks would take **12+ hours**. The pre-screener scans all 50 in
**~20 seconds** and picks the top 5 most promising.

### Two Scoring Modes

| Mode | Default? | Score Range | Purpose |
|---|---|---|---|
| **Buy-biased** | Yes | -25 to +100 | Find stocks worth buying |
| **Direction-agnostic** | No | 0 to 100 | Find where action is happening |

### Buy-Biased Mode (Default)

Designed for **new candidate selection**. Rewards bullish signals, penalizes bearish:

| Signal | Bullish (🟢) | Bearish (🔴) |
|---|---|---|
| Volume spike + price up | Accumulation → reward | — |
| Volume spike + price down | — | Distribution → penalty |
| Positive 1d/5d momentum | Full points | — |
| Negative 1d/5d momentum | — | Penalty (negative score) |
| Near 3-month high | Breakout potential → reward | — |
| Near 3-month low | — | Falling knife → penalty |
| Bullish news keywords | Bonus | — |
| Bearish news keywords | — | Penalty |

### Keyword Sentiment Analysis

Headlines from 6 India RSS feeds are scanned for ~30 bullish and ~30 bearish keywords:

**Bullish**: profit, growth, upgrade, breakout, rally, surge, beat, outperform,
dividend, buyback, acquisition, partnership, contract, approval, recovery, rebound

**Bearish**: loss, fraud, downgrade, crash, plunge, slump, probe, investigation,
penalty, crisis, layoff, warning, miss, default, debt, decline, sell-off

Sentiment = `(positive_hits - negative_hits) / total_hits`, clamped to [-1.0, +1.0].

### Standalone Usage

```bash
# Top 10 buy candidates (default buy-biased)
python -m tradingagents.trading.pre_screener 10

# Top 10 by raw interestingness (direction-agnostic)
python -m tradingagents.trading.pre_screener 10 --action
```

Example output:
```
🔍 Top 10 NIFTY 50 — BUY-BIASED screening

#    Ticker              Score    Vol     1d%     5d%  News  Sent  Reasons
─────────────────────────────────────────────────────────────────────────────────────────────────
1    TITAN.NS           +64.2   4.1x   +4.7%   +2.8%    1  +1.0  🟢 accumulation, breakout, bullish news
2    APOLLOHOSP.NS      +57.7   2.4x   +3.3%   +6.0%    0     —  🟢 accumulation, strong momentum
3    ASIANPAINT.NS      +52.3   2.1x   +2.7%   +6.4%    0     —  🟢 accumulation, breakout
```

### Python API

```python
from tradingagents.trading.pre_screener import pre_screen, NIFTY_50

# Buy-biased (default) — for new candidates
candidates = pre_screen(NIFTY_50, top_n=5, buy_bias=True)

# Direction-agnostic — for market scanning
movers = pre_screen(NIFTY_50, top_n=10, buy_bias=False)

for r in candidates:
    print(f"{r.ticker}: score={r.total_score:+.1f}, "
          f"sentiment={r.news_sentiment:+.1f}, "
          f"reasons={r.reasons}")
```

### Scoring Components

| Component | Weight | What It Measures |
|---|---|---|
| Volume | 25 pts | Today’s volume vs 20-day average |
| News | 25 pts | RSS mentions × keyword sentiment |
| 5-day momentum | 20 pts | 5-day return direction + magnitude |
| 1-day momentum | 15 pts | 1-day return direction + magnitude |
| 3-month proximity | 15 pts | Distance from 3-month high/low |

### How Buy-Bias Filters Work (Real Example)

SBI dropped 6.7% on 2026-05-09 with 2.9x volume and 6 news mentions:

| Mode | Rank | Score | Why |
|---|---|---|---|
| Direction-agnostic | **#1** | +88.5 | Big crash = interesting |
| Buy-biased | **Not in top 10** | Negative | 🔴 Distribution + falling knife + negative momentum |

---

## 12. Interactive CLI

The built-in CLI provides a rich TUI with live progress:

```bash
tradingagents
```

It walks you through:
1. **Provider selection** — OpenAI, Anthropic, Google, Ollama, etc.
2. **Model selection** — quick and deep thinking models
3. **Analyst selection** — which analysts to run
4. **Ticker input** — what stock to analyze
5. **Live dashboard** — see agents working in real-time
6. **Final report** — formatted decision with investment thesis

---

## 13. Memory & Learning

The framework has a **memory system** that learns from past decisions:

### How It Works

1. **Decision logged** — Each run stores the ticker, date, rating, and full decision
2. **Outcome resolved** — On the next run for the same ticker, the framework
   fetches actual returns and calculates alpha vs benchmark
3. **Reflection generated** — The LLM reflects on what went right/wrong
4. **Context injected** — Past decisions + reflections are fed into future runs

### Enable Checkpoint/Resume

If a run crashes mid-pipeline, checkpointing lets you resume:

```python
config["checkpoint_enabled"] = True
```

State is saved to SQLite after each agent node. Re-run the same
ticker + date to resume from the last successful step.

### Memory Log Location

```
~/.tradingagents/memory/trading_memory.md
```

Override with:
```python
config["memory_log_path"] = "/path/to/memory.md"
```

---

## 14. All Config Options

| Key | Default | Description |
|---|---|---|
| `llm_provider` | `"openai"` | LLM provider (see §6) |
| `deep_think_llm` | `"gpt-5.4"` | Model for deep analysis |
| `quick_think_llm` | `"gpt-5.4-mini"` | Model for tool calls |
| `backend_url` | `None` | Custom API endpoint |
| `max_debate_rounds` | `1` | Bull vs Bear debate rounds |
| `max_risk_discuss_rounds` | `1` | Risk team discussion rounds |
| `max_recur_limit` | `100` | LangGraph recursion limit |
| `checkpoint_enabled` | `False` | Save state for resume |
| `output_language` | `"English"` | Output language |
| `benchmark_ticker` | `"SPY"` | Benchmark index |
| `benchmark_name` | `"S&P 500"` | Benchmark display name |
| `market_context` | `""` | Extra context for agents |
| `global_news_queries` | `None` | Custom news search queries |
| `data_vendors` | See §7 | Data source routing |
| `tool_vendors` | `{}` | Per-tool vendor overrides |
| `memory_log_path` | `~/.tradingagents/...` | Memory log file |
| `memory_log_max_entries` | `None` | Max memory entries |
| `google_thinking_level` | `None` | Gemini thinking depth |
| `openai_reasoning_effort` | `None` | OpenAI reasoning effort |
| `anthropic_effort` | `None` | Claude effort level |

### India-Specific Config

Import `INDIA_CONFIG` for NSE/BSE stocks:

```python
from tradingagents.config_india import INDIA_CONFIG

config = {**DEFAULT_CONFIG, **INDIA_CONFIG}
```

This sets:
- Benchmark → NIFTY 50 (`^NSEI`)
- News → India RSS feeds (ET, Moneycontrol, LiveMint)
- Market context → RBI, FII/DII, SEBI, India VIX, T+1 settlement
- Global news queries → India economy, geopolitics

---

## 15. Troubleshooting

### Ollama: "404 page not found"

The `backend_url` must end with `/v1`:
```python
config["backend_url"] = None  # Let it auto-detect (recommended)
# or explicitly:
config["backend_url"] = "http://localhost:11434/v1"
```

### Ollama hangs on corporate network (proxy)

If your network uses an HTTP proxy, Ollama calls may route through it. Fix:

```python
import os
os.environ["LANGCHAIN_OPENAI_TCP_KEEPALIVE"] = "0"
```

The framework auto-detects Walmart proxy and configures `NO_PROXY` for
`localhost`, but the `langchain-openai` library may override this. The
Ollama client uses an explicit `httpx.Client(proxy=None)` to work around this.

### yfinance: "Could not resolve host"

You're behind a proxy. The framework auto-detects this if you call:
```python
from tradingagents.network import configure_network
configure_network()  # Call BEFORE any yfinance imports
```

### RSS feeds: "407 authenticationrequired"

Corporate proxies block RSS feeds. The pipeline automatically falls back to
yfinance for news data. This is non-fatal.

### Alpha Vantage: "API key not set"

Make sure `data_vendors` explicitly sets `yfinance` for all categories.
A shallow dict merge can drop your defaults:

```python
# ❌ WRONG — replaces entire data_vendors dict
config = {**DEFAULT_CONFIG, "data_vendors": {"news_data": "india_rss"}}

# ✅ RIGHT — include all categories
config["data_vendors"] = {
    "core_stock_apis": "yfinance",
    "technical_indicators": "yfinance",
    "fundamental_data": "yfinance",
    "news_data": "india_rss,yfinance",
}
```

### Pipeline takes too long

| Lever | Impact |
|---|---|
| Smaller model (`qwen3:8b`) | 2–3x faster |
| Fewer analysts | Skip `social` and `news` |
| Fewer debate rounds | `max_debate_rounds: 1` |
| Cloud API | GPT-5.4-mini: ~2 min vs local 14B: ~30 min |

### How to see pipeline progress

LangGraph's `invoke` is blocking — no mid-flight output. To monitor:

```bash
# Check if Ollama is working
curl -s http://localhost:11434/api/ps | python3 -c "
import json, sys
d = json.load(sys.stdin)
for m in d.get('models', []):
    print(f'{m[\"name\"]}: expires={m[\"expires_at\"]}')
"
```

If the model's `expires_at` keeps refreshing, the pipeline is running.

---

## Example: Full Script

```python
"""Analyze RELIANCE.NS using local Ollama and paper trade the result."""

import os, logging
from dotenv import load_dotenv

load_dotenv()
os.environ["LANGCHAIN_OPENAI_TCP_KEEPALIVE"] = "0"

from tradingagents.network import configure_network
configure_network()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.config_india import INDIA_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.trading import create_broker, resolve_trade, execute_trade, portfolio_report

# Config
config = {
    **DEFAULT_CONFIG,
    **INDIA_CONFIG,
    "llm_provider": "ollama",
    "deep_think_llm": "qwen3:32b",
    "quick_think_llm": "qwen3:14b",
}

# Broker
broker = create_broker({"trading_mode": "paper", "initial_capital": 10_00_000.0})

# Pipeline
graph = TradingAgentsGraph(config=config)
final_state, signal = graph.propagate("RELIANCE.NS", "2026-05-09")

print(f"Decision: {signal}")
print(final_state["final_trade_decision"])

# Trade
trade = resolve_trade("RELIANCE.NS", signal, final_state["final_trade_decision"], broker)
if not trade.skipped:
    order = execute_trade(trade, broker)
    print(f"Executed: {order.side} x{order.quantity} @ ₹{order.price}")

# Report
print(portfolio_report(broker))
```

---

## File Structure

```
TradingAgents/
├── run_pipeline.py                # Single-ticker pipeline + paper trade
├── main.py                        # Simple example script
├── cli/                           # Interactive TUI (Rich + Typer)
│   └── main.py
├── tradingagents/
│   ├── default_config.py          # All config defaults
│   ├── config_india.py            # India market presets
│   ├── network.py                 # Auto-detect proxy/VPN
│   ├── graph/
│   │   └── trading_graph.py       # Main orchestrator (LangGraph)
│   ├── agents/
│   │   ├── analysts/              # 4 analyst nodes
│   │   ├── researchers/           # Bull/Bear debate
│   │   ├── managers/              # Research + Portfolio managers
│   │   ├── risk_mgmt/             # 3-way risk discussion
│   │   ├── trader/                # Trade proposal
│   │   └── schemas.py             # Structured output schemas
│   ├── dataflows/                 # yfinance, Alpha Vantage, India RSS
│   ├── llm_clients/               # Provider adapters
│   └── trading/
│       ├── broker.py              # Abstract BrokerInterface
│       ├── paper_broker.py        # SQLite paper trading
│       ├── angel_one.py           # Angel One SmartAPI
│       ├── executor.py            # Rating → sized trade with guardrails
│       ├── pre_screener.py        # Heuristic stock screener (2 modes, no LLM)
│       ├── daily_runner.py        # Multi-ticker daily orchestrator
│       └── portfolio.py           # Reporting + P&L
└── data/
    └── paper_portfolio.db         # Paper trading database (auto-created)
```

---

*Built with LangGraph, LangChain, yfinance, and a whole lot of chai ☕*
