"""Pre-screener — fast, buy-biased stock ranking with ZERO LLM calls.

Scans all NIFTY 50 tickers using lightweight data (price, volume, news
headlines) and scores each stock by **buy opportunity quality**.  Designed
to run in 1-3 minutes before the heavy agent pipeline kicks in.

Two scoring modes:

- ``buy_bias=True`` (default): Favors stocks with positive momentum,
  bullish news sentiment, and breakout patterns.  Penalizes falling
  knives and negative headlines.  Use for **new candidate selection**.

- ``buy_bias=False``: Direction-agnostic "interestingness" scoring.
  Big moves in either direction score high.  Use for **holdings review**
  or general market scanning.

Usage::

    from tradingagents.trading.pre_screener import pre_screen, NIFTY_50

    # Buy candidates (default)
    candidates = pre_screen(NIFTY_50, top_n=5)

    # Direction-agnostic scan
    movers = pre_screen(NIFTY_50, top_n=10, buy_bias=False)
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


# ── Scoring weights ─────────────────────────────────────────────────────
_WEIGHTS = {
    "volume": 25,
    "momentum_5d": 20,
    "momentum_1d": 15,
    "news": 25,
    "extreme": 15,
}


# ── Headline sentiment keywords ─────────────────────────────────────────
_BULLISH_KEYWORDS = frozenset({
    "profit", "growth", "record", "upgrade", "breakout", "rally", "surge",
    "boom", "expansion", "beat", "outperform", "strong", "bullish", "gain",
    "rise", "high", "dividend", "buyback", "acquisition", "partnership",
    "contract", "approval", "launch", "robust", "positive", "recovery",
    "rebound", "top pick", "overweight", "buy", "target raised",
    "order win", "deal", "margin improvement", "beat estimates",
})

_BEARISH_KEYWORDS = frozenset({
    "loss", "fraud", "scam", "downgrade", "crash", "plunge", "slump",
    "decline", "weak", "bearish", "probe", "investigation", "penalty",
    "fine", "default", "debt", "crisis", "layoff", "restructuring",
    "warning", "miss", "underperform", "sell-off", "cut", "downgrade",
    "recall", "ban", "negative", "concern", "risk", "fell", "drop",
    "target cut", "underweight", "sell", "disappointing", "below estimate",
})


@dataclass
class ScreenResult:
    """Score + metadata for a single screened ticker."""

    ticker: str
    total_score: float = 0.0
    volume_ratio: float = 0.0
    return_1d: float = 0.0         # 1-day return %
    return_5d: float = 0.0         # 5-day return %
    news_mentions: int = 0
    news_sentiment: float = 0.0    # -1.0 (bearish) to +1.0 (bullish)
    pct_from_52w_high: float = 0.0
    pct_from_52w_low: float = 0.0
    reasons: list[str] = field(default_factory=list)
    error: Optional[str] = None


# ── Public API ───────────────────────────────────────────────────────────

def pre_screen(
    universe: list[str] | None = None,
    top_n: int = 5,
    trade_date: str | None = None,
    exclude: set[str] | None = None,
    news_enabled: bool = True,
    buy_bias: bool = True,
) -> list[ScreenResult]:
    """Score and rank stocks — no LLM, pure heuristics.

    Args:
        universe: Tickers to scan. Defaults to :data:`NIFTY_50`.
        top_n: How many top scorers to return.
        trade_date: Date string (YYYY-MM-DD). Defaults to today.
        exclude: Tickers to skip (e.g. already-held positions).
        news_enabled: If False, skip RSS fetch (faster, less accurate).
        buy_bias: If True, favor positive momentum and bullish sentiment.
            If False, score by raw "interestingness" (direction-agnostic).

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

    mode_label = "BUY-BIASED" if buy_bias else "DIRECTION-AGNOSTIC"
    logger.info("Pre-screening %d tickers (%s mode)...", len(tickers_to_scan), mode_label)

    # ── Step 1: Batch-fetch price data (single yfinance call) ────────
    price_data = _fetch_price_data(tickers_to_scan)

    # ── Step 2: Fetch news with sentiment (lightweight RSS scan) ─────
    news_signals: dict[str, _NewsSignal] = {}
    if news_enabled:
        news_signals = _fetch_news_signals(tickers_to_scan, trade_date)

    # ── Step 3: Score each ticker ────────────────────────────────────
    results: list[ScreenResult] = []
    for ticker in tickers_to_scan:
        signal = news_signals.get(ticker, _NewsSignal())
        result = _score_ticker(ticker, price_data.get(ticker), signal, buy_bias)
        results.append(result)

    # ── Step 4: Rank and return top N ────────────────────────────────
    results.sort(key=lambda r: r.total_score, reverse=True)
    top = results[:top_n]

    logger.info("Pre-screen results (%s):", mode_label)
    for i, r in enumerate(top, 1):
        reasons_str = ", ".join(r.reasons) if r.reasons else "baseline"
        logger.info(
            "  %d. %s — score %.1f (%s)", i, r.ticker, r.total_score, reasons_str
        )

    return top


# ── Data classes ─────────────────────────────────────────────────────────

@dataclass
class _NewsSignal:
    """Lightweight news signal for one ticker (internal use)."""

    mentions: int = 0
    sentiment: float = 0.0   # -1.0 to +1.0
    positive: int = 0
    negative: int = 0


# ── Price data fetching ──────────────────────────────────────────────────

def _fetch_price_data(tickers: list[str]) -> dict[str, dict]:
    """Batch-download 3 months of OHLCV for all tickers in one call."""
    logger.info("Fetching price data for %d tickers (batch)...", len(tickers))

    try:
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
            hist = data if len(tickers) == 1 else data[ticker].dropna(how="all")
            if hist.empty or len(hist) < 5:
                continue
            result[ticker] = {"hist": hist}
        except (KeyError, AttributeError):
            continue

    logger.info("Got price data for %d / %d tickers", len(result), len(tickers))
    return result


# ── News signals (mentions + sentiment, no LLM) ─────────────────────────

def _headline_sentiment(text: str) -> tuple[int, int]:
    """Count bullish and bearish keyword hits in a headline/summary.

    Returns (positive_hits, negative_hits).
    """
    lower = text.lower()
    pos = sum(1 for kw in _BULLISH_KEYWORDS if kw in lower)
    neg = sum(1 for kw in _BEARISH_KEYWORDS if kw in lower)
    return pos, neg


def _fetch_news_signals(
    tickers: list[str],
    trade_date: str,
) -> dict[str, _NewsSignal]:
    """Fetch news mentions + keyword sentiment for each ticker.

    Uses the same India RSS feeds as the main pipeline.  Counts keyword
    hits to compute a sentiment score without any LLM call.
    """
    from tradingagents.dataflows.india_news import (
        _ALL_FEEDS,
        _company_name,
        _fetch_entries,
    )

    logger.info("Scanning RSS feeds for news signals...")

    end_dt = datetime.strptime(trade_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=2)
    entries = _fetch_entries(_ALL_FEEDS, start_dt, end_dt)

    logger.info("Fetched %d RSS articles, analyzing sentiment for %d tickers...",
                len(entries), len(tickers))

    signals: dict[str, _NewsSignal] = {}
    for ticker in tickers:
        search_term = _company_name(ticker).lower()
        total_pos, total_neg, mentions = 0, 0, 0

        for entry in entries:
            title = entry.get("title", "").lower()
            summary = entry.get("summary", "").lower()
            if search_term not in title and search_term not in summary:
                continue

            mentions += 1
            # Analyze sentiment on the combined title + summary
            combined = entry.get("title", "") + " " + entry.get("summary", "")
            pos, neg = _headline_sentiment(combined)
            total_pos += pos
            total_neg += neg

        if mentions > 0:
            total_hits = total_pos + total_neg
            sentiment = (total_pos - total_neg) / total_hits if total_hits > 0 else 0.0
            sentiment = max(-1.0, min(1.0, sentiment))  # clamp
            signals[ticker] = _NewsSignal(
                mentions=mentions,
                sentiment=sentiment,
                positive=total_pos,
                negative=total_neg,
            )

    return signals


# ── Scoring logic ────────────────────────────────────────────────────────

def _score_ticker(
    ticker: str,
    price_data: dict | None,
    news: _NewsSignal,
    buy_bias: bool,
) -> ScreenResult:
    """Compute a composite score for one ticker.

    When ``buy_bias=True``:
      - Positive momentum → full points; negative → penalty
      - Volume spike + price up → accumulation (good); + price down → distribution (bad)
      - Bullish news sentiment → bonus; bearish → penalty
      - Near 3-month high → breakout potential; near low → falling knife penalty

    When ``buy_bias=False``:
      - Absolute momentum magnitude (direction-agnostic)
      - Volume spike always scores
      - News mentions count regardless of sentiment
      - Either extreme scores
    """
    result = ScreenResult(
        ticker=ticker,
        news_mentions=news.mentions,
        news_sentiment=news.sentiment,
    )

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

        # ── Extract raw metrics ──────────────────────────────────────
        latest_vol = float(volumes.iloc[-1])
        avg_vol_20d = float(volumes.tail(20).mean())
        vol_ratio = latest_vol / avg_vol_20d if avg_vol_20d > 0 else 1.0
        result.volume_ratio = vol_ratio

        ret_1d = float((closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2])
        result.return_1d = ret_1d * 100

        ret_5d = float(
            (closes.iloc[-1] - closes.iloc[-6]) / closes.iloc[-6]
        ) if len(closes) >= 6 else ret_1d
        result.return_5d = ret_5d * 100

        high_3mo = float(closes.max())
        low_3mo = float(closes.min())
        current = float(closes.iloc[-1])

        pct_from_high = (high_3mo - current) / high_3mo if high_3mo > 0 else 0
        pct_from_low = (current - low_3mo) / low_3mo if low_3mo > 0 else 0
        result.pct_from_52w_high = pct_from_high * 100
        result.pct_from_52w_low = pct_from_low * 100

        # ── Score components (each -1.0 to +1.0) ────────────────────
        if buy_bias:
            scores = _score_buy_biased(
                vol_ratio, ret_1d, ret_5d, pct_from_high, pct_from_low,
                news, result.reasons,
            )
        else:
            scores = _score_direction_agnostic(
                vol_ratio, ret_1d, ret_5d, pct_from_high, pct_from_low,
                news, result.reasons,
            )

        # ── Composite score (weighted sum) ───────────────────────────
        result.total_score = (
            scores["volume"] * _WEIGHTS["volume"]
            + scores["momentum_1d"] * _WEIGHTS["momentum_1d"]
            + scores["momentum_5d"] * _WEIGHTS["momentum_5d"]
            + scores["news"] * _WEIGHTS["news"]
            + scores["extreme"] * _WEIGHTS["extreme"]
        )

    except Exception as e:
        result.error = str(e)
        logger.warning("Error scoring %s: %s", ticker, e)

    return result


def _score_buy_biased(
    vol_ratio: float,
    ret_1d: float,
    ret_5d: float,
    pct_from_high: float,
    pct_from_low: float,
    news: _NewsSignal,
    reasons: list[str],
) -> dict[str, float]:
    """Score components biased toward buy opportunities.

    Each component returns a value in [-1.0, +1.0].
    Positive = bullish signal.  Negative = bearish penalty.
    """

    # ── Volume: spike + direction alignment ──────────────────────────
    # Volume spike on an up day = accumulation (bullish)
    # Volume spike on a down day = distribution (bearish, but mild penalty
    # since it could be capitulation)
    if vol_ratio > 1.5:
        if ret_1d > 0:
            vol_score = min((vol_ratio - 1.0) / 2.0, 1.0)
            reasons.append(f"🟢 vol {vol_ratio:.1f}x + price up (accumulation)")
        else:
            vol_score = -0.3 * min((vol_ratio - 1.0) / 2.0, 1.0)
            reasons.append(f"🟡 vol {vol_ratio:.1f}x + price down (distribution)")
    else:
        vol_score = 0.0

    # ── 1-day momentum: directional ──────────────────────────────────
    # Positive return → reward.  Negative return → penalty.
    if ret_1d > 0.02:
        mom_1d = min(ret_1d / 0.05, 1.0)
        reasons.append(f"🟢 1d +{ret_1d*100:.1f}%")
    elif ret_1d < -0.02:
        mom_1d = max(ret_1d / 0.05, -1.0)
        reasons.append(f"🔴 1d {ret_1d*100:.1f}%")
    else:
        mom_1d = ret_1d / 0.05  # mild linear reward/penalty

    # ── 5-day momentum: directional ──────────────────────────────────
    if ret_5d > 0.03:
        mom_5d = min(ret_5d / 0.08, 1.0)
        reasons.append(f"🟢 5d +{ret_5d*100:.1f}%")
    elif ret_5d < -0.03:
        mom_5d = max(ret_5d / 0.08, -1.0)
        reasons.append(f"🔴 5d {ret_5d*100:.1f}%")
    else:
        mom_5d = ret_5d / 0.08

    # ── News: mentions × sentiment ───────────────────────────────────
    # High mentions + positive sentiment → big bonus
    # High mentions + negative sentiment → big penalty
    # No mentions → neutral
    if news.mentions > 0:
        mention_factor = min(news.mentions / 5.0, 1.0)
        # Sentiment ranges from -1 to +1; scale to [-1, +1]
        # Neutral sentiment (0.0) with mentions → small positive (news = attention)
        news_score = mention_factor * (0.2 + 0.8 * news.sentiment)
        news_score = max(-1.0, min(1.0, news_score))

        if news.sentiment > 0.2:
            reasons.append(f"🟢 {news.mentions} news (bullish: +{news.positive}/-{news.negative})")
        elif news.sentiment < -0.2:
            reasons.append(f"🔴 {news.mentions} news (bearish: +{news.positive}/-{news.negative})")
        else:
            reasons.append(f"🟡 {news.mentions} news (mixed: +{news.positive}/-{news.negative})")
    else:
        news_score = 0.0

    # ── Proximity: near high = breakout, near low = falling knife ────
    if pct_from_high < 0.03:
        extreme_score = max(0, 1.0 - pct_from_high / 0.03)
        reasons.append(f"🟢 near 3mo high ({pct_from_high*100:.1f}% away)")
    elif pct_from_low < 0.05:
        # Near 3-month low → penalty (falling knife)
        extreme_score = -0.5 * max(0, 1.0 - pct_from_low / 0.05)
        reasons.append(f"🔴 near 3mo low ({pct_from_low*100:.1f}% above)")
    else:
        extreme_score = 0.0

    return {
        "volume": vol_score,
        "momentum_1d": mom_1d,
        "momentum_5d": mom_5d,
        "news": news_score,
        "extreme": extreme_score,
    }


def _score_direction_agnostic(
    vol_ratio: float,
    ret_1d: float,
    ret_5d: float,
    pct_from_high: float,
    pct_from_low: float,
    news: _NewsSignal,
    reasons: list[str],
) -> dict[str, float]:
    """Score components by raw interestingness (direction doesn't matter).

    Each component returns 0.0 to 1.0 (no penalties, only magnitude).
    """

    # ── Volume spike ─────────────────────────────────────────────────
    vol_score = min((vol_ratio - 1.0) / 2.0, 1.0) if vol_ratio > 1.0 else 0.0
    if vol_ratio > 1.5:
        reasons.append(f"volume spike {vol_ratio:.1f}x")

    # ── 1-day momentum (absolute) ────────────────────────────────────
    mom_1d = min(abs(ret_1d) / 0.03, 1.0)
    if abs(ret_1d) > 0.02:
        direction = "up" if ret_1d > 0 else "down"
        reasons.append(f"1d {direction} {abs(ret_1d)*100:.1f}%")

    # ── 5-day momentum (absolute) ────────────────────────────────────
    mom_5d = min(abs(ret_5d) / 0.06, 1.0)
    if abs(ret_5d) > 0.04:
        direction = "up" if ret_5d > 0 else "down"
        reasons.append(f"5d {direction} {abs(ret_5d)*100:.1f}%")

    # ── News heat (count only, no sentiment) ─────────────────────────
    news_score = min(news.mentions / 5.0, 1.0)
    if news.mentions >= 2:
        reasons.append(f"{news.mentions} news mentions")

    # ── Either extreme ───────────────────────────────────────────────
    near_high = max(0, 1.0 - pct_from_high / 0.05) if pct_from_high < 0.05 else 0
    near_low = max(0, 1.0 - pct_from_low / 0.10) if pct_from_low < 0.10 else 0
    extreme_score = max(near_high, near_low)

    if pct_from_high < 0.03:
        reasons.append(f"near 3mo high ({pct_from_high*100:.1f}% away)")
    elif pct_from_low < 0.05:
        reasons.append(f"near 3mo low ({pct_from_low*100:.1f}% above)")

    return {
        "volume": vol_score,
        "momentum_1d": mom_1d,
        "momentum_5d": mom_5d,
        "news": news_score,
        "extreme": extreme_score,
    }


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

    top_n = 10
    buy_bias = "--action" not in sys.argv  # default buy-biased

    for arg in sys.argv[1:]:
        if arg.isdigit():
            top_n = int(arg)

    mode_label = "BUY-BIASED" if buy_bias else "DIRECTION-AGNOSTIC"
    results = pre_screen(top_n=top_n, buy_bias=buy_bias)

    print(f"\n🔍 Top {top_n} NIFTY 50 — {mode_label} screening\n")
    print(
        f"{'#':<4} {'Ticker':<18} {'Score':>6} {'Vol':>6} "
        f"{'1d%':>7} {'5d%':>7} {'News':>5} {'Sent':>5}  Reasons"
    )
    print("─" * 100)
    for i, r in enumerate(results, 1):
        reasons_str = ", ".join(r.reasons) if r.reasons else "—"
        sent_str = f"{r.news_sentiment:+.1f}" if r.news_mentions > 0 else "  —"
        print(
            f"{i:<4} {r.ticker:<18} {r.total_score:>+5.1f} {r.volume_ratio:>5.1f}x "
            f"{r.return_1d:>+6.1f}% {r.return_5d:>+6.1f}% {r.news_mentions:>4} {sent_str:>5}  "
            f"{reasons_str}"
        )
