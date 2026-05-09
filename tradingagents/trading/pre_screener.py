"""Pre-screener — fast, heuristic stock ranking with ZERO LLM calls.

Scans all NIFTY 50 tickers using lightweight data (price, volume, news
mentions) and scores each stock by "interestingness".  Designed to run
in 1-3 minutes before the heavy agent pipeline kicks in.

Usage::

    from tradingagents.trading.pre_screener import pre_screen, NIFTY_50

    ranked = pre_screen(NIFTY_50, top_n=5)
    for r in ranked:
        print(f"{r.ticker}: {r.total_score:.1f}  ({r.reasons})")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)

# ── Full NIFTY 50 universe ───────────────────────────────────────────────
NIFTY_50 = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "BAJFINANCE.NS", "MARUTI.NS", "TITAN.NS",
    "SUNPHARMA.NS", "TATAMOTORS.NS", "ONGC.NS", "NTPC.NS", "POWERGRID.NS",
    "HCLTECH.NS", "WIPRO.NS", "ADANIENT.NS", "ADANIPORTS.NS", "ULTRACEMCO.NS",
    "TECHM.NS", "ASIANPAINT.NS", "NESTLEIND.NS", "JSWSTEEL.NS", "TATASTEEL.NS",
    "BAJAJFINSV.NS", "BAJAJ-AUTO.NS", "DRREDDY.NS", "CIPLA.NS", "COALINDIA.NS",
    "EICHERMOT.NS", "GRASIM.NS", "DIVISLAB.NS", "APOLLOHOSP.NS", "HEROMOTOCO.NS",
    "BPCL.NS", "TATACONSUM.NS", "BRITANNIA.NS", "HINDALCO.NS", "INDUSINDBK.NS",
    "SBILIFE.NS", "HDFCLIFE.NS", "M&M.NS", "SHRIRAMFIN.NS", "TRENT.NS",
]


# ── Scoring weights (tweak these to change selection behavior) ───────────
_WEIGHTS = {
    "volume_spike": 25,     # Unusual volume = something is happening
    "momentum_5d": 20,      # 5-day price move (magnitude, not direction)
    "momentum_1d": 15,      # 1-day price move
    "news_heat": 25,        # News mentions from RSS feeds
    "near_extreme": 15,     # Near 52-week high or low
}


@dataclass
class ScreenResult:
    """Score + metadata for a single screened ticker."""

    ticker: str
    total_score: float = 0.0
    volume_ratio: float = 0.0      # today_vol / 20d_avg_vol
    return_1d: float = 0.0         # 1-day return %
    return_5d: float = 0.0         # 5-day return %
    news_mentions: int = 0         # count from RSS
    pct_from_52w_high: float = 0.0 # how far below 52-week high
    pct_from_52w_low: float = 0.0  # how far above 52-week low
    reasons: list[str] = field(default_factory=list)
    error: Optional[str] = None


# ── Core screening logic ─────────────────────────────────────────────────

def pre_screen(
    universe: list[str] | None = None,
    top_n: int = 5,
    trade_date: str | None = None,
    exclude: set[str] | None = None,
    news_enabled: bool = True,
) -> list[ScreenResult]:
    """Score and rank stocks by interestingness — no LLM, pure heuristics.

    Args:
        universe: Tickers to scan. Defaults to :data:`NIFTY_50`.
        top_n: How many top scorers to return.
        trade_date: Date string (YYYY-MM-DD). Defaults to today.
        exclude: Tickers to skip (e.g. already-held positions).
        news_enabled: If False, skip RSS fetch (faster, less accurate).

    Returns:
        Top *top_n* :class:`ScreenResult` objects, highest score first.
    """
    universe = universe or NIFTY_50
    exclude = exclude or set()
    trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")
    tickers_to_scan = [t for t in universe if t not in exclude]

    if not tickers_to_scan:
        logger.warning("Pre-screener: no tickers to scan after exclusions")
        return []

    logger.info("Pre-screening %d tickers...", len(tickers_to_scan))

    # ── Step 1: Batch-fetch price data (single yfinance call) ────────
    price_data = _fetch_price_data(tickers_to_scan)

    # ── Step 2: Fetch news mentions (lightweight RSS scan) ───────────
    news_counts: dict[str, int] = {}
    if news_enabled:
        news_counts = _fetch_news_mentions(tickers_to_scan, trade_date)

    # ── Step 3: Score each ticker ────────────────────────────────────
    results: list[ScreenResult] = []
    for ticker in tickers_to_scan:
        result = _score_ticker(ticker, price_data.get(ticker), news_counts.get(ticker, 0))
        results.append(result)

    # ── Step 4: Rank and return top N ────────────────────────────────
    results.sort(key=lambda r: r.total_score, reverse=True)
    top = results[:top_n]

    logger.info("Pre-screen results:")
    for i, r in enumerate(top, 1):
        reasons_str = ", ".join(r.reasons) if r.reasons else "baseline"
        logger.info(
            "  %d. %s — score %.1f (%s)", i, r.ticker, r.total_score, reasons_str
        )

    return top


# ── Price data fetching ──────────────────────────────────────────────────

def _fetch_price_data(tickers: list[str]) -> dict[str, dict]:
    """Batch-download 3 months of OHLCV for all tickers in one call.

    Returns a dict of ticker → {hist: DataFrame, info: dict} for each
    ticker that returned data.
    """
    logger.info("Fetching price data for %d tickers (batch)...", len(tickers))

    try:
        # yfinance batch download: single HTTP call for all tickers
        data = yf.download(
            tickers,
            period="3mo",
            group_by="ticker",
            auto_adjust=True,
            threads=True,
            progress=False,
        )
    except Exception as e:
        logger.error("Batch price download failed: %s", e)
        return {}

    result: dict[str, dict] = {}

    for ticker in tickers:
        try:
            if len(tickers) == 1:
                # yf.download returns flat DataFrame for single ticker
                hist = data
            else:
                hist = data[ticker].dropna(how="all")

            if hist.empty or len(hist) < 5:
                continue

            result[ticker] = {"hist": hist}
        except (KeyError, AttributeError):
            continue

    logger.info("Got price data for %d / %d tickers", len(result), len(tickers))
    return result


# ── News mentions (lightweight RSS, no LLM) ─────────────────────────────

def _fetch_news_mentions(
    tickers: list[str],
    trade_date: str,
) -> dict[str, int]:
    """Count how many RSS articles mention each ticker's company name.

    Uses the same India RSS feeds as the main pipeline but does NOT pass
    anything to an LLM — just counts keyword hits per ticker.
    """
    from tradingagents.dataflows.india_news import (
        _ALL_FEEDS,
        _company_name,
        _fetch_entries,
    )

    logger.info("Scanning RSS feeds for news mentions...")

    end_dt = datetime.strptime(trade_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=2)  # last 48 hours of news
    entries = _fetch_entries(_ALL_FEEDS, start_dt, end_dt)

    logger.info("Fetched %d RSS articles, matching against %d tickers...", len(entries), len(tickers))

    counts: dict[str, int] = {}
    for ticker in tickers:
        search_term = _company_name(ticker).lower()
        count = sum(
            1 for e in entries
            if search_term in e["title"].lower() or search_term in e.get("summary", "").lower()
        )
        if count > 0:
            counts[ticker] = count

    return counts


# ── Scoring logic ────────────────────────────────────────────────────────

def _score_ticker(
    ticker: str,
    price_data: dict | None,
    news_mentions: int,
) -> ScreenResult:
    """Compute a composite interestingness score for one ticker."""
    result = ScreenResult(ticker=ticker, news_mentions=news_mentions)

    if price_data is None:
        result.error = "No price data"
        return result

    hist = price_data["hist"]

    try:
        closes = hist["Close"].dropna()
        volumes = hist["Volume"].dropna()

        if len(closes) < 5 or len(volumes) < 5:
            result.error = "Insufficient data"
            return result

        # ── Volume spike ─────────────────────────────────────────────
        latest_vol = float(volumes.iloc[-1])
        avg_vol_20d = float(volumes.tail(20).mean())
        vol_ratio = latest_vol / avg_vol_20d if avg_vol_20d > 0 else 1.0
        result.volume_ratio = vol_ratio

        # Score: 0 at ratio=1.0, maxes out at ratio=3.0+
        vol_score = min((vol_ratio - 1.0), 2.0) / 2.0 if vol_ratio > 1.0 else 0.0
        if vol_ratio > 1.5:
            result.reasons.append(f"volume spike {vol_ratio:.1f}x")

        # ── 1-day momentum ───────────────────────────────────────────
        ret_1d = float((closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2])
        result.return_1d = ret_1d * 100

        # Magnitude matters, not direction (both big drop and big gain are interesting)
        mom_1d_score = min(abs(ret_1d) / 0.03, 1.0)  # normalized to ±3%
        if abs(ret_1d) > 0.02:
            direction = "up" if ret_1d > 0 else "down"
            result.reasons.append(f"1d {direction} {abs(ret_1d)*100:.1f}%")

        # ── 5-day momentum ───────────────────────────────────────────
        if len(closes) >= 6:
            ret_5d = float((closes.iloc[-1] - closes.iloc[-6]) / closes.iloc[-6])
        else:
            ret_5d = ret_1d
        result.return_5d = ret_5d * 100

        mom_5d_score = min(abs(ret_5d) / 0.06, 1.0)  # normalized to ±6%
        if abs(ret_5d) > 0.04:
            direction = "up" if ret_5d > 0 else "down"
            result.reasons.append(f"5d {direction} {abs(ret_5d)*100:.1f}%")

        # ── 52-week proximity ────────────────────────────────────────
        high_52w = float(closes.max())
        low_52w = float(closes.min())
        current = float(closes.iloc[-1])

        if high_52w > low_52w:
            pct_from_high = (high_52w - current) / high_52w
            pct_from_low = (current - low_52w) / low_52w if low_52w > 0 else 0
            result.pct_from_52w_high = pct_from_high * 100
            result.pct_from_52w_low = pct_from_low * 100

            # Score: high near 52w extremes (within 5% of high or 10% of low)
            near_high = max(0, 1.0 - pct_from_high / 0.05) if pct_from_high < 0.05 else 0
            near_low = max(0, 1.0 - (pct_from_low / (low_52w * 0.10 / current))) if pct_from_low < 0.10 else 0
            extreme_score = max(near_high, near_low)

            if pct_from_high < 0.03:
                result.reasons.append(f"near 3mo high ({pct_from_high*100:.1f}% away)")
            elif pct_from_low < 0.05:
                result.reasons.append(f"near 3mo low ({pct_from_low*100:.1f}% above)")
        else:
            extreme_score = 0

        # ── News heat ────────────────────────────────────────────────
        # Score: 0 at 0 mentions, maxes at 5+ mentions
        news_score = min(news_mentions / 5.0, 1.0)
        if news_mentions >= 2:
            result.reasons.append(f"{news_mentions} news mentions")

        # ── Composite score (weighted sum, 0-100) ────────────────────
        result.total_score = (
            vol_score * _WEIGHTS["volume_spike"]
            + mom_1d_score * _WEIGHTS["momentum_1d"]
            + mom_5d_score * _WEIGHTS["momentum_5d"]
            + news_score * _WEIGHTS["news_heat"]
            + extreme_score * _WEIGHTS["near_extreme"]
        )

    except Exception as e:
        result.error = str(e)
        logger.warning("Error scoring %s: %s", ticker, e)

    return result


# ── CLI entry point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    from tradingagents.network import configure_network
    configure_network()

    import sys
    top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 5

    results = pre_screen(top_n=top_n)

    print(f"\n🔍 Top {top_n} NIFTY 50 stocks by interestingness:\n")
    print(f"{'Rank':<5} {'Ticker':<18} {'Score':<8} {'Vol':>6} {'1d%':>7} {'5d%':>7} {'News':>5}  Reasons")
    print("─" * 90)
    for i, r in enumerate(results, 1):
        reasons_str = ", ".join(r.reasons) if r.reasons else "—"
        print(
            f"{i:<5} {r.ticker:<18} {r.total_score:<8.1f} {r.volume_ratio:>5.1f}x "
            f"{r.return_1d:>+6.1f}% {r.return_5d:>+6.1f}% {r.news_mentions:>4}  {reasons_str}"
        )
