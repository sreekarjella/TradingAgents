# 🇮🇳 TradingAgents — Indian Markets Project Tracker

> **Owner**: Sreekar
> **Started**: 2026-05-09
> **Status**: 🟢 Phase 0 — COMPLETE ✅
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
| Benchmark index | TBD — `^NSEI` (NIFTY 50) | Replace SPY for alpha calculation | — |
| Broker (paper) | TBD | — | — |
| Broker (real) | TBD | Zerodha / Angel One / Fyers shortlisted | — |
| Indian news sources | TBD | — | — |

---

## 🗺️ Phases & Milestones

### Phase 0: Setup & Validation ← **CURRENT**
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

### Phase 1: India Adaptation (Target: Week 2-3)
> Modify the framework to be India-market-aware

- [ ] Fix ticker handling for `.NS`/`.BO` suffix
- [ ] Replace SPY benchmark with NIFTY 50 (`^NSEI`)
- [ ] Add India-centric global news queries (RBI, FII/DII, monsoon, elections, geopolitics)
- [ ] Add Indian news sources (Economic Times, Moneycontrol, LiveMint RSS)
- [ ] Add India-specific context to analyst prompts (SEBI, circuit limits, T+1)
- [ ] Add India VIX, FII/DII flow data
- [ ] Test with 10-15 popular NSE stocks (RELIANCE, TCS, INFY, HDFCBANK, etc.)
- [ ] Tune debate rounds and prompt quality

### Phase 2: Paper Trading Engine (Target: Week 4-6)
> Build portfolio tracking + simulated trading

- [ ] Design portfolio database schema (SQLite)
- [ ] Build paper trading simulator (virtual cash, order execution)
- [ ] Build daily scheduler (run at 3:30 PM IST market close)
- [ ] Build portfolio review loop (for each holding → analyze → decide)
- [ ] Add position sizing rules (max % per stock, sector limits)
- [ ] Add watchlist scanner (screen NIFTY 50/200 for opportunities)
- [ ] Build daily P&L reporting

### Phase 3: Paper Trading Month (Target: Week 7-10)
> Run paper trading for 4+ weeks, collect performance data

- [ ] Define starting capital (virtual)
- [ ] Define stock universe (which stocks to consider)
- [ ] Run daily for 4 weeks
- [ ] Track: win rate, avg return, max drawdown, alpha vs NIFTY 50
- [ ] Tune prompts based on reflection data
- [ ] Document lessons learned
- [ ] Go/No-Go decision for real money

### Phase 4: Broker Integration (Target: Week 11-13)
> Connect to real Indian broker API

- [ ] Choose broker and get API access
- [ ] Build broker adapter layer (abstract interface)
- [ ] Implement order placement (market/limit orders)
- [ ] Add safety guardrails (max order size, daily loss limit, kill switch)
- [ ] Add error handling (network failures, partial fills, rejected orders)
- [ ] Start with tiny positions (₹1,000-5,000 per trade)

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
| 2026-05-09 | RELIANCE.NS | Indicators | ✅ PASS | SMA50, SMA200, MACD, MACDH, RSI, Bollinger (upper/mid/lower) |

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

---

## 🐛 Known Issues & Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Ollama registry blocked on Walmart network | Can't pull models on VPN | Pull models off-network; they run locally once cached |
| Yahoo Finance blocked on Walmart DNS | yfinance can't fetch data | Use HTTP_PROXY + NO_PROXY for localhost in .env |
| Ollama 500 errors intermittent | Pipeline retries/slows | Context length or thinking tokens; monitor and tune |
| ~20 min per run (1 analyst) | Slow for daily use | Optimize: fewer debate rounds, smaller context, or faster model |
| yfinance Indian news quality is limited | Poor sentiment analysis | Add dedicated Indian news APIs in Phase 1 |
| Insider transaction data spotty for Indian stocks | Weak fundamentals analysis | Add NSE bulk deal data |
| LLMs can hallucinate financial data | Bad trade decisions | Multi-agent debate catches most errors; memory system self-corrects |
| Market hours mismatch (IST vs UTC) | Wrong timing for trades | Add IST-aware scheduling in Phase 2 |
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

---

*Last updated: 2026-05-09*
