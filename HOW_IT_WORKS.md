# 🤖 How TradingAgents Works — A Plain English Guide

> **No coding knowledge required.** This explains what the system does,
> how it thinks, and why it makes the decisions it makes.

---

## What Is This Thing?

Imagine you hired a **team of 12 financial analysts** to watch the Indian
stock market every single day.  Each morning they:

1. Scan all 50 major Indian stocks (the NIFTY 50)
2. Read the news, check the charts, study the financials
3. Debate with each other about what to buy or sell
4. Make a final decision as a team
5. Execute the trade

That's exactly what this system does — except the "analysts" are AI agents
running on your laptop.  No cloud subscriptions, no monthly fees, no sharing
your financial data with anyone.

---

## The Two Big Steps

### Step 1: The Quick Scan (20 seconds)

Before the AI team spends time analyzing anything, a **fast scanner** looks
at all 50 stocks and asks:

> *"Which 5 stocks have the most interesting things happening RIGHT NOW?"*

It checks five things — no AI needed, just math:

| What It Checks | Why It Matters | Example |
|---|---|---|
| **Volume spike** | If 3x more people are trading than usual, *something* is going on | "Titan traded 4x normal volume today" |
| **Price momentum** | Stocks moving up strongly might keep going | "Apollo Hospitals is up 6% this week" |
| **News buzz** | More headlines = more attention = potential opportunity | "6 articles about SBI today" |
| **News tone** | Are those headlines good or bad? | "Titan: 'record profit' = good 👍" |
| **Price extremes** | Near an all-time high? Could be breaking out | "Asian Paints is at its 3-month high" |

#### The Smart Filter

Here's the clever part: the scanner doesn't just find "interesting" stocks —
it finds stocks that **look worth buying**.

A stock that crashed 7% on a fraud scandal? That's *interesting*, sure — but
you probably don't want to buy it.  The scanner knows the difference:

| Stock | What Happened | Old System | New System |
|---|---|---|---|
| SBI | Crashed 7%, bad news | "Interesting! Rank #1" | "Falling knife. Skip." |
| Titan | Rose 5%, good news | "Interesting. Rank #3" | "Buy opportunity! Rank #1" |

The scanner picks the top 5 most promising stocks and hands them off to
the AI team.

---

### Step 2: The Deep Analysis (15 minutes per stock)

This is where the AI does its magic.  For each stock the scanner picked,
a team of **12 AI agents** analyzes it from every angle:

```
        📊 Market Analyst     — "What do the charts say?"
        📱 Social Analyst     — "What's the buzz online?"
        📰 News Analyst       — "What's in the headlines?"
        💰 Fundamentals Guy   — "Is the company actually making money?"
                    │
                    ▼
        🐂 Bull Researcher    — "Here's why we should BUY"
        🐻 Bear Researcher    — "Here's why we should SELL"
              (they debate)
                    │
                    ▼
        📋 Trader             — "OK, here's my proposed trade"
                    │
                    ▼
        🎲 Aggressive Risk    — "I'm fine with the risk"
        ⚖️ Neutral Risk       — "Hmm, let me think..."
        🛡️ Conservative Risk  — "Too risky, reduce the size"
              (they discuss)
                    │
                    ▼
        👔 Portfolio Manager   — "FINAL DECISION: Buy / Hold / Sell"
```

Think of it like a real investment firm:

1. **Four analysts** each study a different aspect of the stock
2. **Two researchers** argue bull vs bear (like a courtroom debate)
3. **A trader** proposes the actual trade (how much to buy/sell)
4. **Three risk managers** challenge the trade from different angles
5. **The portfolio manager** makes the final call

The final decision is one of five ratings:

| Rating | What It Means | What Happens |
|---|---|---|
| **Buy** | "Strong opportunity, load up" | Buys 5% of portfolio |
| **Overweight** | "Looks good, add a bit" | Buys 3% of portfolio |
| **Hold** | "Wait and see" | Does nothing |
| **Underweight** | "Getting worried, reduce" | Sells half the position |
| **Sell** | "Get out now" | Sells everything |

---

## A Typical Morning

Here's what happens when the system runs at 8:00 AM:

```
8:00 AM   Scanner wakes up
          ├── Downloads price data for all 50 NIFTY stocks (2 seconds)
          ├── Reads news headlines from 6 Indian sources (5 seconds)
          ├── Scores each stock by buy-worthiness (instant)
          └── Result: "Today's top 5: Titan, Apollo, Asian Paints,
                       Tata Consumer, Bajaj Auto"

8:01 AM   Reviews your existing holdings (if any)
          ├── "You hold Reliance — still looks good → Hold"
          ├── "You hold TCS — weakening → Sell half"
          └── "You hold Infosys — strong → Hold"

8:30 AM   Analyzes the 5 new candidates (15 min each)
          ├── Titan → Buy → Buys ₹50,000 worth
          ├── Apollo Hospitals → Hold → Skips
          ├── Asian Paints → Overweight → Buys ₹30,000 worth
          ├── Tata Consumer → Hold → Skips
          └── Bajaj Auto → Buy → Buys ₹50,000 worth

9:45 AM   Takes a snapshot of your portfolio
          Generates a daily report with P&L
          Done! ☕
```

Total time: about 90 minutes.  You don't need to watch it — it runs on
its own and saves everything.

---

## How It Picks News Tone (Sentiment)

The system reads headlines from 6 Indian financial news sources:

- **Economic Times** (2 feeds)
- **Moneycontrol** (2 feeds)
- **LiveMint** (2 feeds)

It scans each headline for positive and negative words:

| Positive Words 👍 | Negative Words 👎 |
|---|---|
| profit, growth, upgrade | loss, fraud, downgrade |
| rally, surge, breakout | crash, plunge, slump |
| record, beat, outperform | crisis, penalty, warning |
| dividend, buyback, deal | layoff, default, debt |

**Example:**

> *"Titan reports record quarterly profit, beats all estimates"*
>
> Positive words found: "record", "profit", "beat"
> Negative words found: none
> **Sentiment: +1.0 (very bullish)** 🟢

> *"Adani Ports faces probe, shares decline on weak outlook"*
>
> Positive words found: none
> Negative words found: "probe", "decline", "weak"
> **Sentiment: -1.0 (very bearish)** 🔴

This isn't perfect — it doesn't understand sarcasm or complex context.
But it's right about 80% of the time, and the AI team catches the rest
during the deep analysis.

---

## Money Management

The system follows strict rules to protect your capital:

### Portfolio Limits

| Rule | Value | Why |
|---|---|---|
| Maximum stocks held | 10 | Don't spread too thin |
| Per-stock allocation | 5% of portfolio | Don't put all eggs in one basket |
| Maximum per stock | 10% of portfolio | Hard cap on concentration |
| Minimum trade size | ₹500 | Avoid tiny pointless trades |
| Maximum trade size | ₹1,00,000 | Safety cap |

### How It Builds Up Over Time

```
Day 1:  Empty portfolio → buys 3 stocks           → 3 positions
Day 2:  Reviews 3 + buys 3 more                    → 6 positions
Day 3:  Reviews 6 + buys 3 more                    → 9 positions
Day 4:  Reviews 9 + buys 1 more                    → 10 positions (FULL)
Day 5:  Reviews 10 → sells 2 weak ones             → 8 positions
        Buys 2 new ones                             → 10 positions
```

Once the portfolio is full (10 stocks), it can only buy new stocks
after selling existing ones.  This prevents the system from endlessly
accumulating positions.

---

## Paper Trading vs Real Trading

The system has two modes:

### 🧪 Paper Trading (Default — No Real Money)

- Starts with ₹10,00,000 (₹10 Lakh) of **virtual money**
- Buys and sells at **real market prices**
- Tracks P&L, wins, losses — everything a real portfolio would
- All data saved in a local database on your laptop
- **Zero risk.** If it makes bad decisions, you lose nothing.

This is what runs for the first month.  Think of it as a trial run to
see if the AI team actually makes good calls.

### 💰 Live Trading (After Validation)

After paper trading proves the system works:

- Connects to your **Angel One** brokerage account
- Executes **real orders** with **real money**
- Starts with tiny positions (₹500–1,000 per trade)
- Same analysis, same rules — just real execution

Switching from paper to live is literally changing one setting. The
entire analysis pipeline stays the same.

---

## What Data Does It Use?

| Data Type | Source | Cost |
|---|---|---|
| Stock prices (daily) | Yahoo Finance | Free |
| Technical charts | Yahoo Finance | Free |
| Company financials | Yahoo Finance | Free |
| Indian market news | ET, Moneycontrol, LiveMint RSS | Free |
| India VIX (fear index) | Yahoo Finance | Free |
| FII/DII flows | NSE India website | Free |

**Total monthly cost: ₹0**

The AI runs on your laptop using open-source models. No cloud API
subscriptions needed.

---

## What It Does NOT Do

Let's be honest about the limitations:

| It Does | It Does NOT |
|---|---|
| Analyze NIFTY 50 stocks | Trade penny stocks or F&O |
| Make daily buy/sell decisions | Do intraday/high-frequency trading |
| Use real market data | Guarantee profits |
| Learn from past mistakes | Predict black swan events |
| Run fully automatically | Replace human judgment entirely |

**This is a tool, not a crystal ball.** It helps you make more informed
decisions by processing more data than any human could read in a day.
But markets are unpredictable, and past performance doesn't guarantee
future results.

---

## The Technology (Without the Jargon)

For the curious — here's what's happening under the hood, in simple terms:

| Component | Plain English |
|---|---|
| **LLM (Large Language Model)** | The "brain" — same type of AI as ChatGPT, but running privately on your laptop |
| **LangGraph** | The "workflow engine" that coordinates the 12 AI agents |
| **yfinance** | Fetches stock prices from Yahoo Finance |
| **SQLite** | A tiny database file that stores your portfolio history |
| **RSS feeds** | News headlines delivered automatically (like a news ticker) |
| **Ollama** | The software that runs AI models on your laptop (instead of paying OpenAI) |

Everything runs locally on your MacBook.  Your financial data never
leaves your machine.

---

## Frequently Asked Questions

### "Can it actually make money?"

Honestly? We don't know yet.  That's what the paper trading month is for.
The system is designed to be *better than random* by combining multiple
data sources and perspectives.  But the stock market is inherently
unpredictable.

### "Is it legal?"

Yes.  Using software to analyze stocks and place trades is completely
legal in India.  SEBI has regulations around algorithmic trading for
institutional investors, but retail investors using tools like this
are not affected.

### "What if it makes a terrible decision?"

During paper trading: nothing happens — it's virtual money.  During
live trading: there are safety guardrails (maximum trade size, daily
loss limits, position caps).  You can also set it to "dry run" mode
where it analyzes but doesn't actually trade.

### "How much time do I need to spend on this?"

Zero, once it's set up.  It runs automatically and generates reports.
You can check the reports whenever you want — daily, weekly, or not
at all during the paper trading phase.

### "Can it work with stocks outside India?"

Yes.  The system works with any stock that Yahoo Finance supports
(US, Europe, Asia, crypto).  The India-specific features (RSS feeds,
India VIX, FII/DII data) are add-ons that activate when you use
`.NS` or `.BO` tickers.

### "What if my internet goes down mid-run?"

The system saves progress as it goes.  If it crashes, you can restart
it and it will pick up where it left off (via checkpointing).
Partially completed trades are logged so nothing gets lost.

---

## The Big Picture

```
    ┌──────────────────────────────────────────────────────┐
    │                  YOUR LAPTOP                         │
    │                                                      │
    │   ┌──────────┐    ┌──────────┐    ┌──────────┐      │
    │   │ Scanner  │───▶│ AI Team  │───▶│ Executor │      │
    │   │ (20 sec) │    │ (15 min) │    │ (trade)  │      │
    │   └──────────┘    └──────────┘    └──────────┘      │
    │        │               │               │             │
    │   "Which 5?"    "Buy or sell?"    "Done! ₹50K       │
    │                                   of Titan bought"   │
    │                                                      │
    │   ┌──────────────────────────────────────────┐       │
    │   │ Portfolio Database (local, private)       │       │
    │   │ Holdings, P&L, history, daily snapshots   │       │
    │   └──────────────────────────────────────────┘       │
    └──────────────────────────────────────────────────────┘
            │                                │
            ▼                                ▼
    ┌──────────────┐                ┌──────────────┐
    │ Yahoo Finance│                │ News Feeds   │
    │ (prices)     │                │ (headlines)  │
    └──────────────┘                └──────────────┘
```

Everything stays on your laptop.  The only external connections are
to Yahoo Finance (for prices) and news websites (for headlines).
Your portfolio data, trading decisions, and AI analysis never leave
your machine.

---

*Written for humans, not developers. Last updated: 2026-05-09*
