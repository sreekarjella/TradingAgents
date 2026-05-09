# 🇮🇳 TradingAgents — Indian Markets Project Tracker

> **Owner**: Sreekar
> **Started**: 2026-05-09
> **Status**: 🟢 Phase 2 — Paper Trading Engine (core built)
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
| `tradingagents/trading/__init__.py` | New | 65 | Factory + executor exports |
| `tradingagents/trading/executor.py` | New | 220 | Trade executor: rating → sized order with guardrails |
| `tradingagents/trading/daily_runner.py` | New | 205 | Daily orchestrator: review + scan + snapshot + report |
| `tradingagents/trading/broker.py` | New | 106 | Abstract BrokerInterface + Order/Holding/PortfolioSnapshot |
| `tradingagents/trading/paper_broker.py` | New | 361 | SQLite paper trading (real prices, virtual execution) |
| `tradingagents/trading/angel_one.py` | New | 283 | Angel One SmartAPI (auth, LTP, orders, holdings, funds) |
| `tradingagents/trading/portfolio.py` | New | 116 | P&L reports, daily snapshots, markdown output |
| `tradingagents/network.py` | New | 65 | Auto-detect Walmart vs home network, proxy management |
| `.env` | Modified | +4 | Angel One creds (no hardcoded proxy — auto-detected) |
| `.gitignore` | Modified | +2 | Exclude `data/` (SQLite DB) |

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

*Last updated: 2026-05-09T21:20 IST*
