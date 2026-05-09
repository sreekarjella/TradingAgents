"""India-specific market data: India VIX and FII/DII activity.

Provides two data functions consumed by analyst agents:
- ``get_india_vix_data``: India VIX history via yfinance (``^INDIAVIX``)
- ``get_fii_dii_activity``: FII/DII cash-market flows via NSE public API

Both return markdown-formatted strings matching the project convention.
"""

import logging
from datetime import datetime, timedelta
from http.cookiejar import CookieJar
from typing import Optional
from urllib.request import Request, build_opener, HTTPCookieProcessor

import yfinance as yf

from .stockstats_utils import yf_retry

logger = logging.getLogger(__name__)

_NSE_BASE = "https://www.nseindia.com"
_NSE_FII_DII_URL = f"{_NSE_BASE}/api/fiidiiTradeReact"
_NSE_TIMEOUT = 10
_NSE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# India VIX via yfinance
# ---------------------------------------------------------------------------

def get_india_vix_data(
    curr_date: str,
    look_back_days: int = 30,
) -> str:
    """Fetch India VIX history and return a markdown report.

    Args:
        curr_date: Reference date in ``yyyy-mm-dd`` format.
        look_back_days: Number of calendar days of history to include.

    Returns:
        Markdown-formatted report with VIX values, trend, and interpretation.
    """
    try:
        end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=look_back_days)
        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")

        vix = yf.Ticker("^INDIAVIX")
        hist = yf_retry(lambda: vix.history(start=start_str, end=end_str))

        if hist is None or hist.empty:
            return f"No India VIX data available for {start_str} to {curr_date}"

        closes = hist["Close"]
        latest = closes.iloc[-1]
        prev = closes.iloc[-2] if len(closes) >= 2 else latest
        change_pct = ((latest - prev) / prev) * 100 if prev else 0
        avg_30d = closes.mean()
        high_30d = closes.max()
        low_30d = closes.min()

        # Interpretation
        if latest < 13:
            mood = "Very Low — extreme complacency, potential reversal risk"
        elif latest < 17:
            mood = "Low — market is calm, bullish bias"
        elif latest < 22:
            mood = "Moderate — normal volatility"
        elif latest < 30:
            mood = "Elevated — increased uncertainty, caution warranted"
        else:
            mood = "High — significant fear/uncertainty, potential capitulation"

        # Recent 5-day trend
        recent = closes.tail(5)
        trend_lines = ""
        for date, val in recent.items():
            date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)[:10]
            trend_lines += f"| {date_str} | {val:.2f} |\n"

        report = f"""## India VIX Report ({start_str} to {curr_date})

**Current India VIX:** {latest:.2f} ({change_pct:+.1f}% vs previous session)
**30-Day Average:** {avg_30d:.2f}
**30-Day Range:** {low_30d:.2f} – {high_30d:.2f}
**Market Mood:** {mood}

### Recent 5-Day Trend
| Date | India VIX |
|------|-----------|
{trend_lines}
### Interpretation
- India VIX measures expected 30-day volatility of NIFTY 50 options.
- VIX < 15: Low fear, potentially complacent market.
- VIX 15-20: Normal range, healthy market.
- VIX > 20: Elevated fear, expect larger price swings.
- VIX > 25: High fear, possible capitulation or major event.
- Rising VIX + falling NIFTY = bearish signal (fear increasing).
- Falling VIX + rising NIFTY = bullish confirmation.
"""
        return report

    except Exception as e:
        logger.exception("Error fetching India VIX data")
        return f"Error fetching India VIX data: {e}"


# ---------------------------------------------------------------------------
# FII / DII Activity via NSE
# ---------------------------------------------------------------------------

def _nse_session_fetch(url: str) -> Optional[bytes]:
    """Fetch from NSE API with proper cookie/session handling.

    NSE requires an initial page visit to set session cookies before
    API endpoints will respond.  Returns raw bytes or None on failure.
    """
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))

    headers = {
        "User-Agent": _NSE_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": _NSE_BASE,
    }

    # Step 1: hit the main page to get session cookies
    try:
        req = Request(_NSE_BASE, headers=headers)
        opener.open(req, timeout=_NSE_TIMEOUT)
    except Exception:
        logger.warning("Could not establish NSE session")
        return None

    # Step 2: fetch the actual API endpoint
    try:
        api_req = Request(url, headers=headers)
        resp = opener.open(api_req, timeout=_NSE_TIMEOUT)
        return resp.read()
    except Exception:
        logger.exception("Error fetching NSE API: %s", url)
        return None


def get_fii_dii_activity(
    curr_date: str,
    look_back_days: int = 10,
) -> str:
    """Fetch FII/DII cash market activity from NSE.

    Args:
        curr_date: Reference date in ``yyyy-mm-dd`` format.
        look_back_days: Number of days of data to report (default 10).

    Returns:
        Markdown-formatted report with FII/DII buy/sell/net values.
    """
    import json

    try:
        raw = _nse_session_fetch(_NSE_FII_DII_URL)
        if not raw:
            return _fii_dii_fallback_message(curr_date)

        data = json.loads(raw)

        if not data:
            return _fii_dii_fallback_message(curr_date)

        # NSE returns a list of dicts with keys like:
        # category, date, buyValue, sellValue, netValue
        rows = []
        for entry in data:
            category = entry.get("category", "")
            date_str = entry.get("date", "")
            buy_val = entry.get("buyValue", "N/A")
            sell_val = entry.get("sellValue", "N/A")
            net_val = entry.get("netValue", "N/A")
            rows.append({
                "category": category,
                "date": date_str,
                "buy": buy_val,
                "sell": sell_val,
                "net": net_val,
            })

        if not rows:
            return _fii_dii_fallback_message(curr_date)

        # Separate FII and DII
        fii_rows = [r for r in rows if "FII" in r["category"].upper() or "FPI" in r["category"].upper()]
        dii_rows = [r for r in rows if "DII" in r["category"].upper()]

        report = f"## FII/DII Activity Report (as of {curr_date})\n\n"

        if fii_rows:
            report += "### FII/FPI Activity (₹ Crores)\n"
            report += "| Date | Buy Value | Sell Value | Net Value |\n"
            report += "|------|-----------|------------|----------|\n"
            for r in fii_rows[:look_back_days]:
                report += f"| {r['date']} | {r['buy']} | {r['sell']} | {r['net']} |\n"
            report += "\n"

        if dii_rows:
            report += "### DII Activity (₹ Crores)\n"
            report += "| Date | Buy Value | Sell Value | Net Value |\n"
            report += "|------|-----------|------------|----------|\n"
            for r in dii_rows[:look_back_days]:
                report += f"| {r['date']} | {r['buy']} | {r['sell']} | {r['net']} |\n"
            report += "\n"

        report += """### Interpretation Guide
- **FII/FPI Net Positive**: Foreign investors are buying — bullish signal for market.
- **FII/FPI Net Negative**: Foreign investors are selling — bearish pressure.
- **DII Net Positive**: Domestic institutions buying — often contrarian to FII.
- **FII selling + DII buying**: Common pattern during corrections; DII provides support.
- **Both buying**: Strong bullish signal.
- **Both selling**: Rare but strongly bearish.
- Track the trend over 5-10 sessions, not single days.
"""
        return report

    except Exception as e:
        logger.exception("Error fetching FII/DII data")
        return _fii_dii_fallback_message(curr_date, str(e))


def _fii_dii_fallback_message(curr_date: str, error: str = "") -> str:
    """Return a helpful message when FII/DII data is unavailable."""
    msg = f"## FII/DII Activity Report (as of {curr_date})\n\n"
    msg += "**Data temporarily unavailable from NSE.**\n\n"
    if error:
        msg += f"Reason: {error}\n\n"
    msg += (
        "For manual reference, check:\n"
        "- NSE: https://www.nseindia.com/reports/fii-dii\n"
        "- Moneycontrol: https://www.moneycontrol.com/stocks/marketstats/fii_dii_activity/\n"
        "- Trendlyne: https://trendlyne.com/fii-dii-activity/\n"
    )
    return msg
