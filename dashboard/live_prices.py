"""Live price fetcher for the dashboard.

A single ``yf.download(tickers=[...], period="1d")`` is dramatically
cheaper than N individual ``yf.Ticker(t).history(...)`` calls — yfinance
batches the request and parallelises internally. We also memoize the
result for a few seconds so a user double-clicking Refresh doesn't melt
Yahoo's servers.

Used by the dashboard's Refresh button on the portfolio page.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Iterable

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Short TTL: refresh is a user action, but we still don't want
# back-to-back clicks to hit the network repeatedly.
_PRICE_CACHE_TTL_SECS: float = 15.0

_lock = threading.Lock()
_cache_ts: float = 0.0
_cache_prices: dict[str, float] = {}


def fetch_live_prices(tickers: Iterable[str]) -> dict[str, float]:
    """Return ``{ticker: last_close_price}`` for *tickers*.

    Tickers that fail to resolve (delisted, typo, network error) are
    silently omitted from the result — callers should fall back to
    whatever price they had before.

    The whole call is protected by a 15-second memoization to avoid
    hammering yfinance when a user clicks Refresh repeatedly.
    """
    ticker_list = sorted(set(t for t in tickers if t))
    if not ticker_list:
        return {}

    with _lock:
        global _cache_ts, _cache_prices
        # Cache hit if (a) within TTL AND (b) the previous fetch covered
        # at least everything we're being asked for now. If a new ticker
        # appears we re-fetch.
        cache_covers = set(ticker_list).issubset(_cache_prices.keys())
        if cache_covers and (time.time() - _cache_ts) < _PRICE_CACHE_TTL_SECS:
            return {t: _cache_prices[t] for t in ticker_list}

    try:
        # period="1d" + group_by='ticker' returns the most recent trading
        # day's bar per symbol. ``progress=False`` keeps stdout quiet.
        df = yf.download(
            tickers=ticker_list,
            period="1d",
            interval="1d",
            progress=False,
            group_by="ticker",
            auto_adjust=True,
            threads=True,
        )
    except Exception as exc:  # network, rate limit, anything
        logger.warning("Live price fetch failed for %d tickers: %s", len(ticker_list), exc)
        return {}

    prices: dict[str, float] = {}
    if isinstance(df.columns, pd.MultiIndex):
        # Multi-ticker shape: top-level columns are ticker symbols.
        for t in ticker_list:
            try:
                close = df[t]["Close"].dropna()
                if not close.empty:
                    prices[t] = float(close.iloc[-1])
            except (KeyError, ValueError):
                continue
    else:
        # Single-ticker shape: flat columns, no MultiIndex.
        try:
            close = df["Close"].dropna()
            if not close.empty:
                prices[ticker_list[0]] = float(close.iloc[-1])
        except (KeyError, ValueError):
            pass

    with _lock:
        # Merge into existing cache so partial coverage doesn't evict
        # previously-known prices.
        _cache_prices.update(prices)
        _cache_ts = time.time()

    if len(prices) < len(ticker_list):
        missing = set(ticker_list) - set(prices)
        logger.info("Live price unavailable for: %s", ", ".join(sorted(missing)))

    return prices


def clear_cache() -> None:
    """Drop the price cache. Useful for tests."""
    with _lock:
        global _cache_ts, _cache_prices
        _cache_ts = 0.0
        _cache_prices = {}
