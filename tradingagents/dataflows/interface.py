import logging

import requests

logger = logging.getLogger(__name__)

# Import from vendor-specific modules
from .y_finance import (
    get_YFin_data_online,
    get_stock_stats_indicators_window,
    get_fundamentals as get_yfinance_fundamentals,
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_income_statement as get_yfinance_income_statement,
    get_insider_transactions as get_yfinance_insider_transactions,
)
from .yfinance_news import get_news_yfinance, get_global_news_yfinance
from .india_news import get_news_india_rss, get_global_news_india_rss
from .alpha_vantage_stock import get_stock as get_alpha_vantage_stock
from .alpha_vantage_indicator import get_indicator as get_alpha_vantage_indicator
from .alpha_vantage_fundamentals import (
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_income_statement as get_alpha_vantage_income_statement,
)
from .alpha_vantage_news import (
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_global_news as get_alpha_vantage_global_news,
)
from .alpha_vantage_common import AlphaVantageRateLimitError

# Configuration and routing logic
from .config import get_config

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data"
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators"
        ]
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement"
        ]
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
    }
}

VENDOR_LIST = [
    "yfinance",
    "alpha_vantage",
    "india_rss",
]

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
    },
    # technical_indicators
    "get_indicators": {
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
    },
    # fundamental_data
    "get_fundamentals": {
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
    },
    "get_balance_sheet": {
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
    },
    "get_cashflow": {
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
    },
    "get_income_statement": {
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
    },
    # news_data
    "get_news": {
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
        "india_rss": get_news_india_rss,
    },
    "get_global_news": {
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
        "india_rss": get_global_news_india_rss,
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
    },
}

def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")

def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")

# Phrases that signal an empty/no-data result — triggers fallback to next vendor.
_EMPTY_MARKERS = ("no ", "not found", "no data", "unavailable", "error ")


def _is_empty_result(result) -> bool:
    """Return True if the vendor result indicates no useful data was returned."""
    if not result:
        return True
    if isinstance(result, str) and len(result) < 200:
        lower = result.lower()
        return any(lower.startswith(m) or m in lower for m in _EMPTY_MARKERS)
    return False


def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation with fallback support.

    Fallback is triggered when:
    - The vendor raises ``AlphaVantageRateLimitError``
    - The vendor returns an empty / "no data" result
    """
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(',')]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    # Build fallback chain: primary vendors first, then remaining available vendors
    all_available_vendors = list(VENDOR_METHODS[method].keys())
    fallback_vendors = primary_vendors.copy()
    for vendor in all_available_vendors:
        if vendor not in fallback_vendors:
            fallback_vendors.append(vendor)

    # Build a human-readable summary of the call args for logging
    arg_summary = ", ".join(
        [str(a) for a in args] + [f"{k}={v}" for k, v in kwargs.items()]
    )

    last_result = None
    last_error = None
    for vendor in fallback_vendors:
        if vendor not in VENDOR_METHODS[method]:
            continue

        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        try:
            result = impl_func(*args, **kwargs)
            if _is_empty_result(result) and vendor != fallback_vendors[-1]:
                logger.info(
                    "📊 API: %s(%s) → %s returned empty, trying next vendor",
                    method, arg_summary, vendor,
                )
                last_result = result  # keep it in case all vendors are empty
                continue
            chars = len(result) if isinstance(result, str) else 0
            logger.info(
                "📊 API: %s(%s) → %s (%s chars)",
                method, arg_summary, vendor, f"{chars:,}",
            )
            return result
        except AlphaVantageRateLimitError:
            logger.info(
                "📊 API: %s(%s) → %s rate-limited, trying next vendor",
                method, arg_summary, vendor,
            )
            continue
        except (
            requests.RequestException,
            TimeoutError,
            ConnectionError,
            ValueError,
            KeyError,
        ) as exc:
            # Network / data-shape failures we expect from external vendors.
            # Programming bugs (TypeError, AttributeError, ImportError, etc.)
            # are NOT in this list — they should propagate so we notice them.
            last_error = exc
            logger.info(
                "📊 API: %s(%s) → %s failed (%s), trying next vendor",
                method, arg_summary, vendor, exc,
            )
            continue

    # All vendors tried — return whatever the last one gave us.
    if last_result is not None:
        chars = len(last_result) if isinstance(last_result, str) else 0
        logger.warning(
            "📊 API: %s(%s) → all vendors returned empty (%s chars)",
            method, arg_summary, f"{chars:,}",
        )
        return last_result
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"No available vendor for '{method}'")