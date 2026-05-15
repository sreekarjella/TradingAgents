"""End-to-end Walmart VPN reachability audit for every data source the
trading pipeline can possibly touch.

For each vendor:
  * Attempt a real call with the same proxy/network setup the pipeline uses
  * Report status, latency, and a short content snippet so you can tell
    "200 OK with empty body" apart from "actually returned data"

Run on Walmart VPN to verify which sources are usable end-to-end and which
need workarounds (proxy, alternative endpoint, etc).

Usage:  python tools/audit_walmart_vpn.py
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path
from datetime import datetime, timedelta

# Bootstrap proxy + path
sys.path.insert(0, str(Path(__file__).parent.parent))
from tradingagents.network import configure_network
configure_network()

# Test window (recent week)
END = datetime.now().strftime("%Y-%m-%d")
START = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
TICKER = "RELIANCE.NS"

# Color helpers
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def _ok(msg: str) -> str:  return f"{GREEN}✓ PASS{RESET}  {msg}"
def _warn(msg: str) -> str: return f"{YELLOW}⚠ WARN{RESET}  {msg}"
def _fail(msg: str) -> str: return f"{RED}✗ FAIL{RESET}  {msg}"
def _hdr(msg: str) -> None: print(f"\n{BOLD}── {msg} {'─' * (60 - len(msg))}{RESET}")


def _measure(label: str, fn, ok_check=None):
    """Run fn(), time it, and report based on output (or ok_check callable)."""
    t0 = time.perf_counter()
    try:
        out = fn()
        dt = time.perf_counter() - t0
        # Default check: non-empty, non-error string/object
        if ok_check is not None:
            verdict, detail = ok_check(out)
        elif out is None:
            verdict, detail = "fail", "returned None"
        elif isinstance(out, str) and (
            not out.strip()
            or out.lower().startswith(("no ", "error", "failed"))
            or "no data found" in out.lower()
        ):
            verdict, detail = "warn", f"empty/no-data ({len(out)} chars)"
        elif hasattr(out, "empty") and out.empty:
            verdict, detail = "warn", "empty DataFrame"
        else:
            size = len(out) if hasattr(out, "__len__") else "?"
            detail = f"{size} chars/rows"
        print({
            "pass": _ok, "warn": _warn, "fail": _fail,
        }.get(verdict if isinstance(verdict := locals().get("verdict", "pass"), str) else "pass", _ok)
              (f"{label:35s}  {dt*1000:>6.0f}ms  — {detail}"))
    except Exception as e:
        dt = time.perf_counter() - t0
        msg = str(e).splitlines()[0][:100]
        print(_fail(f"{label:35s}  {dt*1000:>6.0f}ms  — {type(e).__name__}: {msg}"))


# ────────────────────────────────────────────────────────────────────────
# 1. yfinance (Yahoo Finance — query1.finance.yahoo.com)
# ────────────────────────────────────────────────────────────────────────
def test_yfinance():
    _hdr("yfinance — query1.finance.yahoo.com")

    from tradingagents.dataflows.y_finance import (
        get_YFin_data_online,
        get_fundamentals as get_yfinance_fundamentals,
        get_balance_sheet as get_yfinance_balance_sheet,
        get_cashflow as get_yfinance_cashflow,
        get_income_statement as get_yfinance_income_statement,
        get_insider_transactions as get_yfinance_insider_transactions,
    )
    from tradingagents.dataflows.yfinance_news import (
        get_news_yfinance,
        get_global_news_yfinance,
    )
    from tradingagents.dataflows.stockstats_utils import load_ohlcv

    _measure("get_stock_data (OHLCV)",
             lambda: get_YFin_data_online(TICKER, START, END))
    _measure("load_ohlcv (indicator backing)",
             lambda: load_ohlcv(TICKER, END))
    _measure("get_fundamentals",
             lambda: get_yfinance_fundamentals(TICKER, END))
    _measure("get_balance_sheet",
             lambda: get_yfinance_balance_sheet(TICKER, END))
    _measure("get_cashflow",
             lambda: get_yfinance_cashflow(TICKER, END))
    _measure("get_income_statement",
             lambda: get_yfinance_income_statement(TICKER, END))
    _measure("get_news_yfinance",
             lambda: get_news_yfinance(TICKER, START, END))
    _measure("get_global_news_yfinance",
             lambda: get_global_news_yfinance(END, look_back_days=7))
    _measure("get_insider_transactions",
             lambda: get_yfinance_insider_transactions(TICKER))


# ────────────────────────────────────────────────────────────────────────
# 2. Google News RSS — news.google.com
# ────────────────────────────────────────────────────────────────────────
def test_google_rss():
    _hdr("google_rss — news.google.com")
    from tradingagents.dataflows.google_news_rss import (
        get_news_google_rss,
        get_global_news_google_rss,
    )
    _measure("get_news_google_rss",
             lambda: get_news_google_rss(TICKER, START, END))
    _measure("get_global_news_google_rss",
             lambda: get_global_news_google_rss(END, look_back_days=7))


# ────────────────────────────────────────────────────────────────────────
# 3. India RSS — livemint, et, moneycontrol
# ────────────────────────────────────────────────────────────────────────
def test_india_rss():
    _hdr("india_rss — livemint / ET / moneycontrol")
    from tradingagents.dataflows.india_news import (
        get_news_india_rss,
        get_global_news_india_rss,
    )
    # Direct probe of each feed
    import feedparser, httpx
    for name, url in [
        ("livemint markets", "https://www.livemint.com/rss/markets"),
        ("livemint economy", "https://www.livemint.com/rss/economy"),
        ("ET markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
        ("MC business", "https://www.moneycontrol.com/rss/business.xml"),
    ]:
        t0 = time.perf_counter()
        try:
            r = httpx.get(url, timeout=8.0, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0"})
            dt = (time.perf_counter() - t0) * 1000
            if r.status_code == 200 and len(r.content) > 500:
                feed = feedparser.parse(r.content)
                n = len(feed.entries)
                print(_ok(f"{('feed: ' + name):35s}  {dt:>6.0f}ms  — {n} entries, HTTP 200"))
            else:
                print(_fail(f"{('feed: ' + name):35s}  {dt:>6.0f}ms  — HTTP {r.status_code}, {len(r.content)} bytes"))
        except Exception as e:
            dt = (time.perf_counter() - t0) * 1000
            print(_fail(f"{('feed: ' + name):35s}  {dt:>6.0f}ms  — {type(e).__name__}"))

    _measure("get_news_india_rss (aggregator)",
             lambda: get_news_india_rss(TICKER, START, END))
    _measure("get_global_news_india_rss",
             lambda: get_global_news_india_rss(END, look_back_days=7))


# ────────────────────────────────────────────────────────────────────────
# 4. NSE direct — nseindia.com (India VIX, FII/DII)
# ────────────────────────────────────────────────────────────────────────
def test_nse_direct():
    _hdr("NSE direct — nseindia.com")
    from tradingagents.dataflows.india_market_data import (
        get_india_vix_data,
        get_fii_dii_activity,
    )
    _measure("get_india_vix",
             lambda: get_india_vix_data(END, look_back_days=7))
    _measure("get_fii_dii",
             lambda: get_fii_dii_activity(END, look_back_days=7))


# ────────────────────────────────────────────────────────────────────────
# 5. Alpha Vantage — www.alphavantage.co (registered fallback)
# ────────────────────────────────────────────────────────────────────────
def test_alpha_vantage():
    _hdr("alpha_vantage — www.alphavantage.co (fallback only)")
    import os
    if not os.environ.get("ALPHA_VANTAGE_API_KEY"):
        print(_warn("ALPHA_VANTAGE_API_KEY not set — skipping (acceptable; not in default chain)"))
        return
    from tradingagents.dataflows.alpha_vantage_stock import get_stock as get_alpha_vantage_stock
    _measure("alpha_vantage stock",
             lambda: get_alpha_vantage_stock(TICKER, START, END))


# ────────────────────────────────────────────────────────────────────────
# 6. Ollama — localhost:11434 (LLM, local — no network egress)
# ────────────────────────────────────────────────────────────────────────
def test_ollama():
    _hdr("ollama — localhost (LLM, local)")
    import httpx
    t0 = time.perf_counter()
    try:
        r = httpx.get("http://localhost:11434/api/version", timeout=5.0)
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code == 200:
            print(_ok(f"{'ollama version':35s}  {dt:>6.0f}ms  — {r.json()}"))
        else:
            print(_fail(f"ollama returned HTTP {r.status_code}"))
    except Exception as e:
        dt = (time.perf_counter() - t0) * 1000
        print(_fail(f"{'ollama unreachable':35s}  {dt:>6.0f}ms  — {type(e).__name__}"))


# ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{BOLD}╔══════════════════════════════════════════════════════════════╗")
    print(f"║   TradingAgents — Walmart VPN Reachability Audit            ║")
    print(f"╚══════════════════════════════════════════════════════════════╝{RESET}")
    print(f"{DIM}Window: {START} → {END} | Test ticker: {TICKER}{RESET}")

    test_yfinance()
    test_google_rss()
    test_india_rss()
    test_nse_direct()
    test_alpha_vantage()
    test_ollama()

    print(f"\n{DIM}Done.{RESET}\n")
