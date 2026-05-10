# 🇮🇳 TradingAgents — Indian Markets Project Tracker

> **Owner**: Sreekar
> **Started**: 2026-05-09
> **Status**: 🟢 Phase 2 — Paper Trading Engine (core built, config centralized)
> **Repo Base**: [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) v0.2.4

---

## 📋 Project Overview

Build an LLM-powered autonomous trading system for **Indian stock markets** (NSE/BSE) that:
- Researches news, sentiment, politics, geopolitics, and market data daily
- Makes Buy/Overweight/Hold/Underweight/Sell decisions per stock
- Paper trades for 1 month to validate, then connects to a real broker
- Reviews portfolio daily and adjusts positions automatically
- Learns from past decisions via memory/reflection system

---

## 🏗️ Architecture Decisions

| Decision | Choice | Rationale | Date |
|---|---|---|---|
| Base framework | TradingAgents v0.2.4 | Multi-agent LLM trading, LangGraph-based | 2026-05-09 |
| LLM provider | Ollama (local) | Zero cost, privacy, M4 Pro can handle it | 2026-05-09 |
| Deep think model | `qwen3:32b` | Best tool-calling + reasoning combo locally | 2026-05-09 |
| Quick think model | `qwen3:14b` | Fast, solid for analysts and debates | 2026-05-09 |
| Data vendor | yfinance (default) | Free, supports `.NS`/`.BO` Indian tickers | 2026-05-09 |
| Benchmark index | `^NSEI` (NIFTY 50) | Configurable via `benchmark_ticker` | 2026-05-09 |
| India news sources | India RSS (ET, MC, LM) | 6 feeds, `india_rss` vendor, yfinance fallback | 2026-05-09 |
| India market tools | India VIX + FII/DII | VIX via yfinance, FII/DII via NSE API | 2026-05-09 |
| Broker | Angel One SmartAPI | User has account; paper + live via same interface | 2026-05-09 |
| Trading architecture | Abstract BrokerInterface | Paper (SQLite) ↔ Live (Angel One) — one config flip | 2026-05-09 |
| Paper trading DB | SQLite (`data/paper_portfolio.db`) | Lightweight, zero infra, portable | 2026-05-09 |
| Virtual capital | ₹10,00,000 (10 Lakhs) | Configurable via `initial_capital` | 2026-05-09 |
| Pre-screener approach | Heuristic scoring, no LLM | Scan 50 stocks in 20s; pipeline costs ~15 min/stock | 2026-05-09 |
| Screener scoring mode | Buy-biased (default) | New candidates need buy-worthiness, not just "interesting" | 2026-05-09 |
| Sentiment analysis | Keyword heuristics (30+ bullish/bearish words) | Zero LLM cost; ~80% accuracy; pipeline catches the rest | 2026-05-09 |
| Portfolio cap | 10 positions max | Prevents over-diversification; configurable via `--max-positions` | 2026-05-09 |
| Config format | TOML (`config.toml`) | Human-readable, built into Python 3.11+, zero deps | 2026-05-09 |
| Config architecture | Single file + loader with bridge methods | TOML → `TradingConfig` → `.pipeline_config` / `.broker_config` dicts | 2026-05-09 |
| Documentation strategy | 3 docs for 3 audiences | HOW_IT_WORKS (non-tech), HOW_TO_USE (dev), PROJECT_TRACKER (owner) | 2026-05-09 |

---

## 🗺️ Phases & Milestones

### Phase 0: Setup & Validation ✅ COMPLETE
> Get the repo running locally with Ollama, test with an Indian stock

- [x] Clone TradingAgents repo
- [x] Analyze repo architecture and capabilities
- [x] Choose LLM provider (Ollama) and models (Qwen3)
- [x] Create project tracker (this doc)
- [x] Install Ollama models (`qwen3:32b`, `qwen3:14b`) — ⚠️ must pull off Walmart VPN (registry.ollama.ai blocked)
- [x] Create Python venv and install TradingAgents dependencies
- [x] Run first test: `RELIANCE.NS` analysis ✅ SELL decision (2026-05-09)
- [x] Validate: price data works for Indian stocks ✅ (249 days of OHLCV via proxy)
- [x] Validate: technical indicators work ✅ (SMA50, SMA200, MACD, RSI, Bollinger Bands)
- [x] Validate: fundamentals data works ✅ (PE, MarketCap, 52W range)
- [x] Validate: news data quality for Indian stocks ✅ (3 articles found)
- [x] Validate: full pipeline end-to-end (market analyst only) ✅ ~20 min runtime
- [x] Document what works and what breaks ✅ (see test results below)

### Phase 1: India Adaptation ← **CURRENT** (near-complete)
> Modify the framework to be India-market-aware

- [x] Fix ticker handling for `.NS`/`.BO` suffix (already works via `build_instrument_context`)
- [x] Replace SPY benchmark with NIFTY 50 (`^NSEI`) — configurable via `benchmark_ticker`
- [x] Add India-centric global news queries (RBI, FII/DII, geopolitics) — via `global_news_queries`
- [x] Add Indian news sources (Economic Times, Moneycontrol, LiveMint RSS) — `india_news.py`, 6 feeds, 26 tests ✅
- [x] Add India-specific context to analyst prompts (SEBI, circuit limits, T+1) — via `market_context`
- [x] Add India VIX data — via yfinance `^INDIAVIX`, mood interpretation (Low→High)
- [x] Add FII/DII flow data — via NSE API with session cookie handling, graceful fallback
- [x] Wire India tools into market_analyst + news_analyst (auto-detected from config)
- [x] Config: `india_rss,yfinance` news fallback chain in `config_india.py`
- [ ] Test with 10-15 popular NSE stocks (RELIANCE, TCS, INFY, HDFCBANK, etc.)
- [ ] Tune debate rounds and prompt quality

### Phase 2: Paper Trading Engine ← **CURRENT** (core built)
> Build portfolio tracking + simulated trading

- [x] Design portfolio database schema (SQLite: orders, holdings, daily_snapshots, config)
- [x] Build abstract BrokerInterface (Order, Holding, PortfolioSnapshot dataclasses)
- [x] Build PaperBroker — virtual cash, order execution at real prices, SQLite persistence
- [x] Build AngelOneBroker — SmartAPI integration (auth, LTP, orders, holdings, funds)
- [x] Build factory: `create_broker({'trading_mode': 'paper'|'live'})` — one config flip
- [x] Build portfolio reporting (markdown P&L, daily snapshots, benchmark tracking)
- [x] Validate: BUY/SELL execution, weighted avg price, P&L, rejection guards ✅
- [x] Wire into TradingAgents pipeline (agent decision → auto paper trade) ✅
- [x] Build trade executor — resolve_trade() + execute_trade() with position sizing + guardrails ✅
- [x] Build daily runner — review holdings → scan universe → snapshot → report ✅
- [x] Add position sizing rules (Buy=5%, Overweight=3%, Underweight=50%, Sell=100%) ✅
- [x] Add watchlist scanner (top 20 NIFTY 50 default universe) ✅
- [x] Build portfolio review loop (review holdings first, then scan new) ✅
- [x] Build pre-screener — heuristic scoring of all 50 NIFTY stocks in ~20 seconds ✅
- [x] Add buy-biased scoring mode for new candidate selection ✅
- [x] Add keyword sentiment analysis on RSS headlines (30+ bullish + 30+ bearish keywords) ✅
- [x] Add direction-agnostic mode for holdings review (`--action` flag) ✅
- [x] Add portfolio position cap (MAX_POSITIONS=10, buy slots tracking) ✅
- [x] Wire pre-screener into daily runner (screen 50 → pick top 5 → pipeline) ✅
- [x] Centralize all config into `config.toml` — single user-editable file ✅
- [x] Build config loader with bridge methods for backward compatibility ✅
- [x] Make executor accept guardrails from config (no hardcoded constants) ✅
- [x] Make pre-screener accept weights + keywords from config ✅
- [x] Add `--config=path.toml` CLI flag to daily runner ✅
- [x] Add config verifier: `python -m tradingagents.config_loader` ✅
- [x] Write HOW_IT_WORKS.md — plain-English guide for non-technical readers ✅
- [ ] Build daily scheduler (run at 3:30 PM IST market close)

### Phase 3: Paper Trading Month (Target: Week 4-7)
> Run paper trading for 4+ weeks, collect performance data

- [ ] Define stock universe (NIFTY 50 default)
- [ ] Run daily for 4 weeks
- [ ] Track: win rate, avg return, max drawdown, alpha vs NIFTY 50
- [ ] Tune prompts based on reflection data
- [ ] Document lessons learned
- [ ] Go/No-Go decision for real money

### Phase 4: Micro Real Trading (Target: Week 8-10)
> Flip config flag → live execution via Angel One SmartAPI

- [x] ~~Choose broker~~ — Angel One SmartAPI ✅
- [x] ~~Build broker adapter layer~~ — BrokerInterface + AngelOneBroker ✅
- [x] ~~Implement order placement~~ — MARKET + LIMIT, DELIVERY product type ✅
- [ ] Add Angel One credentials to `.env` (API key, client ID, password, TOTP)
- [ ] Add safety guardrails (max order size, daily loss limit, kill switch)
- [ ] Add error handling (network failures, partial fills, rejected orders)
- [ ] Start with micro positions (₹500-1,000 per trade)

### Phase 5: Production Hardening (Ongoing)
> Monitoring, alerts, scaling

- [ ] Trade notification bot (Telegram/WhatsApp)
- [ ] Audit log for SEBI compliance
- [ ] Backtesting engine
- [ ] Gradual position size scaling
- [ ] Performance dashboard

---

## 🖥️ Hardware & Environment

| Component | Details |
|---|---|
| Machine | MacBook Pro M4 Pro |
| Chip | Apple M4 Pro (14 cores: 10P + 4E) |
| RAM | 48 GB unified memory |
| Ollama version | 0.23.2 |
| Python | 3.x (via `uv` venv) |
| OS | macOS (posix) |

---

## 📊 Test Results Log

| Date | Ticker | Phase | Result | Notes |
|---|---|---|---|---|
| 2026-05-09 | RELIANCE.NS | Phase 0 | ✅ SELL | Full pipeline: market analyst→debate→trader→risk→PM. ~20 min runtime. |
| 2026-05-09 | RELIANCE.NS | Data test | ✅ PASS | yfinance price/fundamentals/news all work via Walmart proxy |
| 2026-05-09 | RELIANCE.NS | Phase 1 | ✅ UNDERWEIGHT | India-adapted pipeline: NIFTY 50 bench, India news, market context. JioMart losses, D/E cited |
| 2026-05-09 | — | India RSS | ✅ 26/26 tests | ET, Moneycontrol, LiveMint RSS feeds. 30 company name mappings. |
| 2026-05-09 | — | India VIX | ✅ builds OK | yfinance `^INDIAVIX`, mood interpretation, 5-day trend table |
| 2026-05-09 | — | FII/DII | ✅ builds OK | NSE API with session cookies, fallback message with manual links |
| 2026-05-09 | — | Paper Broker | ✅ all tests | BUY/SELL, weighted avg, P&L, rejection guards, daily snapshot |
| 2026-05-09 | RELIANCE.NS | Angel One LIVE | ✅ ₹1,435.20 | Auth+TOTP+session+symbol(-EQ)+LTP+funds from home network |
| 2026-05-09 | — | Executor | ✅ all tests | Buy 5%/Overweight 3%/Hold/Sell 100%/guardrails — all correct |
| 2026-05-09 | — | Pre-screener (agnostic) | ✅ 50 stocks/22s | SBIN #1 (88.5), BRITANNIA #2 (74.3), TITAN #3 (68.3) — big movers ranked |
| 2026-05-09 | — | Pre-screener (buy-biased) | ✅ 50 stocks/18s | TITAN #1 (+64.2), APOLLO #2 (+57.7), ASIANPAINT #3 (+52.3) — SBI/BRIT filtered out |
| 2026-05-09 | — | Keyword sentiment | ✅ live RSS | ADANIPORTS: -0.5 (1 pos, 3 neg keywords). TITAN: +1.0 (4 pos, 0 neg) |
| 2026-05-09 | — | Buy-bias filter | ✅ validated | Falling knives (SBI -6.7%, BRIT -5.1%) excluded from buy candidates |
| 2026-05-09 | — | Config loader | ✅ all imports | config.toml loaded, all 17 pipeline_config keys, 7 broker_config keys, weights/sizing/guardrails bridged |
| 2026-05-09 | — | Config verifier | ✅ passes | `python -m tradingagents.config_loader` — all sections valid, weights sum to 100 |

---

## 💰 Cost Tracking

| Month | LLM Cost | Broker Cost | Data Cost | Total |
|---|---|---|---|---|
| Month 1 (setup) | $0 (local) | $0 | $0 | **$0** |
| Month 2 (paper) | $0 (local) | $0 | $0 | **$0** |
| Month 3+ (real) | TBD | TBD | TBD | TBD |

---

## 📝 Decision Log

| Date | Decision | Context |
|---|---|---|
| 2026-05-09 | Use Ollama local LLMs instead of paid APIs | Zero cost for paper trading phase, M4 Pro 48GB can handle Qwen3:32b |
| 2026-05-09 | Cannot use Walmart Element/Code Puppy LLMs | Personal project — must use personal infra only |
| 2026-05-09 | Qwen3:32b for deep think, Qwen3:14b for quick think | Best tool-calling + reasoning at this RAM budget |
| 2026-05-09 | Configurable benchmark, not hardcoded India | Keep framework market-agnostic; India is a config overlay |
| 2026-05-09 | India RSS as fallback chain (`india_rss,yfinance`) | RSS feeds are free + India-specific; yfinance as safety net |
| 2026-05-09 | Delegate news module to python-programmer agent | Parallel workstreams: agent built RSS while laila built VIX/FII |
| 2026-05-09 | Angel One as broker (not Zerodha/Fyers) | User already has Angel One account; SmartAPI is free |
| 2026-05-09 | Option D: paper first → micro live | Paper via SQLite, live via same interface — one config flip |
| 2026-05-09 | Collapsed Phase 2 + 4 | Broker adapter built alongside paper engine — no need for separate phase |
| 2026-05-09 | Pre-screener: buy-biased default | New candidates need positive-momentum bias; direction-agnostic for holdings review |
| 2026-05-09 | Keyword sentiment over LLM sentiment | Zero cost, ~80% accuracy, runs in <1 sec for all 50 stocks. Pipeline (with LLM) catches the remaining 20% |
| 2026-05-09 | Two scoring modes, one module | Same `pre_screener.py` handles both buy-biased and action modes. DRY over separate modules |
| 2026-05-09 | TOML for all config, not scattered Python constants | One file to rule them all. Users edit `config.toml`, never touch Python code |
| 2026-05-09 | Config loader with bridge methods | `TradingConfig.pipeline_config` and `.broker_config` produce existing dict shapes — zero breaking changes |
| 2026-05-09 | Pass config through function params, not globals | Functions like `resolve_trade()` accept `guardrails=` kwarg — explicit, testable, no hidden state |
| 2026-05-09 | Three-doc strategy | Technical/non-technical/tracker — each audience gets what they need without wading through noise |

---

## 🐛 Known Issues & Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Ollama registry blocked on Walmart network | Can't pull models on VPN | Pull models off-network; they run locally once cached |
| Yahoo Finance blocked on Walmart DNS | yfinance can't fetch data | Auto-detect via `network.py` — proxy on Walmart, direct at home |
| Ollama 500 errors intermittent | Pipeline retries/slows | Context length or thinking tokens; monitor and tune |
| ~20 min per run (1 analyst) | Slow for daily use | Optimize: fewer debate rounds, smaller context, or faster model |
| yfinance Indian news quality is limited | Poor sentiment analysis | ✅ Mitigated: India RSS feeds (ET, MC, LM) added |
| Insider transaction data spotty for Indian stocks | Weak fundamentals analysis | Add NSE bulk deal data |
| NSE API requires session cookies | FII/DII data fragile | Built cookie-based session handler + fallback links |
| LLMs can hallucinate financial data | Bad trade decisions | Multi-agent debate catches most errors; memory system self-corrects |
| Market hours mismatch (IST vs UTC) | Wrong timing for trades | Add IST-aware scheduling in Phase 2 |
| Angel One session expiry | Auth token expires mid-day | Re-auth on API error; TOTP auto-rotates via pyotp |
| Accidental live trades | Real money loss | Default mode is `paper`; live requires explicit config + creds |
| SEBI regulation changes for algo trading | Legal risk | Monitor SEBI circulars, start with manual approval step |

---

## 📎 Useful Links

- **Repo**: https://github.com/TauricResearch/TradingAgents
- **Paper**: https://arxiv.org/abs/2412.20138
- **How It Works (non-technical)**: [HOW_IT_WORKS.md](HOW_IT_WORKS.md)
- **How to Use (developer guide)**: [HOW_TO_USE.md](HOW_TO_USE.md)
- **Ollama**: https://ollama.com
- **Qwen3 Model Card**: https://huggingface.co/Qwen/Qwen3-32B
- **yfinance Docs**: https://github.com/ranaroussi/yfinance
- **NSE India**: https://www.nseindia.com
- **Zerodha Kite API**: https://kite.trade/docs/connect/v3/
- **Angel One SmartAPI**: https://smartapi.angelone.in/docs
- **Angel One SmartAPI Python SDK**: https://pypi.org/project/smartapi-python/
- **PyOTP (TOTP for Angel One)**: https://pypi.org/project/pyotp/

---

## 🏗️ Files Added/Modified

### Phase 2: Trading Package (new)

| File | Type | Lines | Description |
|---|---|---|---|
| `config.toml` | New | 193 | Single config file — every tunable knob, heavily commented |
| `tradingagents/config_loader.py` | New | 459 | TOML loader + TradingConfig with bridge methods |
| `tradingagents/trading/__init__.py` | New | 68 | Factory + executor + screener exports |
| `tradingagents/trading/executor.py` | New | 296 | Trade executor: rating → sized order with config-driven guardrails |
| `tradingagents/trading/pre_screener.py` | New | 574 | Heuristic stock screener: 2 modes, config-driven weights + keywords |
| `tradingagents/trading/daily_runner.py` | New | 380 | Daily orchestrator: loads config.toml, passes all params through |
| `tradingagents/trading/broker.py` | New | 106 | Abstract BrokerInterface + Order/Holding/PortfolioSnapshot |
| `tradingagents/trading/paper_broker.py` | New | 361 | SQLite paper trading (real prices, virtual execution) |
| `tradingagents/trading/angel_one.py` | New | 283 | Angel One SmartAPI (auth, LTP, orders, holdings, funds) |
| `tradingagents/trading/portfolio.py` | New | 116 | P&L reports, daily snapshots, markdown output |
| `tradingagents/network.py` | New | 65 | Auto-detect Walmart vs home network, proxy management |
| `.env` | Modified | +4 | Angel One creds (no hardcoded proxy — auto-detected) |
| `.gitignore` | Modified | +2 | Exclude `data/` (SQLite DB) |

### Documentation

| File | Type | Lines | Description |
|---|---|---|---|
| `HOW_IT_WORKS.md` | New | 375 | Plain-English guide for non-technical readers |
| `HOW_TO_USE.md` | New | 969 | Developer guide: CLI, Python API, config, troubleshooting |
| `PROJECT_TRACKER.md` | New | ~250 | This file — architecture decisions, phase tracking, test log |

### Phase 1: India Adaptation

| File | Type | Lines | Description |
|---|---|---|---|
| `tradingagents/config_india.py` | New | 45 | Pre-built India config (NIFTY 50, news queries, market context) |
| `tradingagents/dataflows/india_news.py` | New | 186 | RSS news from ET, Moneycontrol, LiveMint (6 feeds) |
| `tradingagents/dataflows/india_market_data.py` | New | 247 | India VIX + FII/DII data fetching |
| `tradingagents/agents/utils/india_market_tools.py` | New | 56 | LangChain tool wrappers for VIX + FII/DII |
| `tests/test_india_news.py` | New | ~150 | 26 unit tests for India RSS module |
| `tradingagents/default_config.py` | Modified | +5 | Added benchmark_ticker, benchmark_name, market_context, global_news_queries |
| `tradingagents/graph/trading_graph.py` | Modified | +2 | SPY → config benchmark_ticker |
| `tradingagents/graph/reflection.py` | Modified | +3 | Dynamic benchmark name in alpha calc |
| `tradingagents/dataflows/yfinance_news.py` | Modified | +8 | Config-driven global news queries |
| `tradingagents/dataflows/interface.py` | Modified | +4 | Registered india_rss vendor |
| `tradingagents/agents/utils/agent_utils.py` | Modified | +5 | market_context injection |
| `tradingagents/agents/analysts/market_analyst.py` | Modified | +13 | Auto-inject India VIX + FII/DII tools |
| `tradingagents/agents/analysts/news_analyst.py` | Modified | +13 | Auto-inject India VIX + FII/DII tools |
| `test_smoke.py` | Modified | — | Updated for India config |
| `test_multi_india.py` | New | 105 | Batch test for 10 NSE blue-chips |

---

---

## 🔍 Pre-Screener — How It Works

The pre-screener scans all 50 NIFTY stocks in ~20 seconds with **zero LLM calls**.
It produces a ranked list of candidates for the expensive pipeline (~15 min/stock).

### Two Scoring Modes

| Mode | Flag | Score Range | Used For |
|---|---|---|---|
| **Buy-biased** (default) | — | -25 to +100 | New stock candidate selection |
| **Direction-agnostic** | `--action` | 0 to 100 | Holdings review, market scanning |

### Scoring Components (100 points max)

| Component | Weight | Buy-Biased | Direction-Agnostic |
|---|---|---|---|
| Volume | 25 pts | Spike + price up = 🟢, spike + price down = 🔴 | Any spike = good |
| News | 25 pts | Mentions × keyword sentiment (+/-) | Mention count only |
| 5-day momentum | 20 pts | Positive = reward, negative = penalty | Absolute magnitude |
| 1-day momentum | 15 pts | Positive = reward, negative = penalty | Absolute magnitude |
| 3mo proximity | 15 pts | Near high = 🟢 breakout, near low = 🔴 falling knife | Either extreme = interesting |

### Keyword Sentiment (30+ words each)

| Bullish | Bearish |
|---|---|
| profit, growth, upgrade, breakout, rally, surge | loss, fraud, downgrade, crash, plunge, slump |
| beat, outperform, strong, gain, dividend, buyback | probe, penalty, crisis, layoff, warning, miss |
| acquisition, partnership, contract, approval | default, debt, sell-off, decline, weak |

Sentiment = `(positive_hits - negative_hits) / total_hits`, clamped to [-1.0, +1.0].

### Real Example (2026-05-09)

| Stock | Agnostic Rank | Buy-Biased Rank | Why the difference |
|---|---|---|---|
| SBIN.NS (-6.7%) | #1 (88.5) | Not in top 10 | 🔴 Negative momentum + distribution + falling knife |
| BRITANNIA.NS (-5.1%) | #2 (74.3) | Not in top 10 | 🔴 Volume spike on down day = distribution |
| TITAN.NS (+4.7%) | #3 (68.3) | **#1 (+64.2)** | 🟢 Accumulation + breakout + bullish news |
| ADANIPORTS.NS (+1.6%) | #6 (51.6) | #6 (+34.3) | 🔴 Bearish news sentiment (-0.5) docked points |

*Last updated: 2026-05-09T24:50 IST*
