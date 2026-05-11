"""LangChain tool wrappers for India-specific market data.

Exposes India VIX and FII/DII activity as tools that analysts can call.
These are opt-in tools — only added when India config is active.
"""

import logging
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.india_market_data import (
    get_fii_dii_activity,
    get_india_vix_data,
)

logger = logging.getLogger(__name__)


@tool
def get_india_vix(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int, "Number of days of VIX history"] = 30,
) -> str:
    """Retrieve India VIX (volatility index) data and trend analysis.

    India VIX measures expected 30-day volatility of NIFTY 50 options.
    Useful for gauging market fear/greed and setting position sizes.

    Args:
        curr_date: Current date in yyyy-mm-dd format.
        look_back_days: Number of days of history (default 30).

    Returns:
        Markdown report with VIX values, trend, and interpretation.
    """
    result = get_india_vix_data(curr_date, look_back_days)
    logger.info(
        "📊 API: get_india_vix(%s, look_back=%d) → %s chars",
        curr_date, look_back_days, f"{len(result):,}",
    )
    return result


@tool
def get_fii_dii(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int, "Number of sessions to include"] = 10,
) -> str:
    """Retrieve FII (Foreign Institutional Investor) and DII (Domestic
    Institutional Investor) cash market activity from NSE.

    FII/DII flows are a key indicator for Indian markets — net FII buying
    is bullish, net selling is bearish.  DII often acts as a contrarian
    counterbalance.

    Args:
        curr_date: Current date in yyyy-mm-dd format.
        look_back_days: Number of trading sessions to report (default 10).

    Returns:
        Markdown report with buy/sell/net values and interpretation guide.
    """
    result = get_fii_dii_activity(curr_date, look_back_days)
    logger.info(
        "📊 API: get_fii_dii(%s, look_back=%d) → %s chars",
        curr_date, look_back_days, f"{len(result):,}",
    )
    return result
