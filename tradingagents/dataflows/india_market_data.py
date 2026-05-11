"""India-specific market data: India VIX and FII/DII activity.

Multi-source approach with graceful fallback:

**India VIX:**
1. yfinance ``^INDIAVIX`` (historical data)
2. NSE ``/api/allIndices`` via curl_cffi (current-day VIX)

**FII/DII:**
1. NSE ``/api/fiidiiTradeReact`` via curl_cffi (browser-impersonated)
2. Graceful markdown with manual reference links

The key improvement over the original: curl_cffi impersonates a real
Chrome browser's TLS fingerprint, which is what NSE's anti-bot detection
checks.  Plain ``urllib`` or ``requests`` get blocked because their TLS
handshake looks like a bot.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import yfinance as yf

from .stockstats_utils import yf_retry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# NSE API constants
# ---------------------------------------------------------------------------

_NSE_BASE = "https://www.nseindia.com"
_NSE_ALL_INDICES_URL = f"{_NSE_BASE}/api/allIndices"
_NSE_FII_DII_URL = f"{_NSE_BASE}/api/fiidiiTradeReact"
_NSE_TIMEOUT = 15
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0

# yfinance ticker variants to try for India VIX (some break periodically)
_VIX_TICKERS = ["^INDIAVIX", "INDIAVIX.NS", "NIFVIX.NS"]


# ═══════════════════════════════════════════════════════════════════════════
# NSE Client — curl_cffi with browser impersonation
# ═══════════════════════════════════════════════════════════════════════════

class _NseClient:
    """Lightweight NSE API client using curl_cffi for TLS fingerprint impersonation.

    NSE blocks requests that don't look like real browsers.  curl_cffi's
    ``impersonate`` feature sends a TLS Client Hello that matches Chrome,
    bypassing their fingerprint check.

    Usage::

        client = _NseClient()
        data = client.fetch_json("/api/allIndices")
        client.close()
    """

    def __init__(self) -> None:
        self._session = None
        self._cookies_warmed = False

    def _ensure_session(self):
        """Lazily create the curl_cffi session."""
        if self._session is not None:
            return

        try:
            from curl_cffi import requests as cf_requests
            self._session = cf_requests.Session(
                impersonate="chrome120",
                timeout=_NSE_TIMEOUT,
            )
        except ImportError:
            logger.warning(
                "curl_cffi not installed — NSE API fallback disabled. "
                "Install with: pip install curl_cffi"
            )
            self._session = None

    def _warm_cookies(self) -> bool:
        """Hit the NSE homepage to collect session cookies.

        Returns True if cookies were obtained successfully.
        """
        if self._cookies_warmed:
            return True

        self._ensure_session()
        if self._session is None:
            return False

        try:
            resp = self._session.get(_NSE_BASE, timeout=_NSE_TIMEOUT)
            if resp.status_code == 200 and len(self._session.cookies) > 0:
                self._cookies_warmed = True
                logger.debug(
                    "NSE session warmed — %d cookies obtained",
                    len(self._session.cookies),
                )
                return True
            logger.debug("NSE homepage returned %d", resp.status_code)
        except Exception as exc:
            logger.debug("NSE cookie warmup error: %s", exc)

        return False

    def fetch_json(self, path: str) -> Optional[Any]:
        """Fetch a JSON endpoint from NSE with retry + cookie warmup.

        Args:
            path: Full URL or path starting with ``/api/...``.

        Returns:
            Parsed JSON (dict or list), or None on failure.
        """
        url = path if path.startswith("http") else f"{_NSE_BASE}{path}"

        for attempt in range(_MAX_RETRIES):
            if not self._warm_cookies():
                # Cookies failed — reset session and retry
                self._reset()
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.info("NSE cookie warmup failed, retrying in %.0fs", delay)
                time.sleep(delay)
                continue

            try:
                resp = self._session.get(url, timeout=_NSE_TIMEOUT)
                if resp.status_code == 200:
                    return resp.json()

                if resp.status_code == 401:
                    # Session expired — reset and retry
                    logger.info("NSE session expired (401), re-warming cookies")
                    self._reset()
                    continue

                logger.warning(
                    "NSE API %s returned HTTP %d", path, resp.status_code
                )

            except Exception as exc:
                logger.debug(
                    "NSE API fetch failed (attempt %d/%d): %s",
                    attempt + 1, _MAX_RETRIES, exc,
                )
                self._reset()

            if attempt < _MAX_RETRIES - 1:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                time.sleep(delay)

        return None

    def _reset(self) -> None:
        """Close and recreate the session for a fresh retry."""
        self.close()
        self._session = None
        self._cookies_warmed = False

    def close(self) -> None:
        """Explicitly close the underlying session."""
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
            self._cookies_warmed = False


# Module-level client — reused across calls within a single pipeline run.
# Lazy-initialized on first use.
_nse_client: Optional[_NseClient] = None


def _get_nse_client() -> _NseClient:
    """Return the module-level NSE client, creating it if needed."""
    global _nse_client
    if _nse_client is None:
        _nse_client = _NseClient()
    return _nse_client


# ═══════════════════════════════════════════════════════════════════════════
# India VIX
# ═══════════════════════════════════════════════════════════════════════════

def get_india_vix_data(
    curr_date: str,
    look_back_days: int = 30,
) -> str:
    """Fetch India VIX data and return a markdown report.

    **Source chain:**
    1. yfinance historical data (multiple ticker variants)
    2. NSE ``/api/allIndices`` for current-day VIX snapshot

    Args:
        curr_date: Reference date in ``yyyy-mm-dd`` format.
        look_back_days: Calendar days of history to include.

    Returns:
        Markdown-formatted report with VIX values, trend, and interpretation.
    """
    # Source 1: yfinance historical data
    report = _vix_from_yfinance(curr_date, look_back_days)
    if report:
        return report

    # Source 2: NSE allIndices API (current-day snapshot only)
    report = _vix_from_nse_api(curr_date)
    if report:
        return report

    return (
        f"## India VIX Report (as of {curr_date})\n\n"
        "**Data temporarily unavailable** from all sources "
        "(yfinance and NSE API).\n\n"
        "For manual reference:\n"
        "- NSE: https://www.nseindia.com/market-data/india-vix\n"
        "- Moneycontrol: https://www.moneycontrol.com/indian-indices/india-vix-702.html\n"
    )


def _vix_from_yfinance(curr_date: str, look_back_days: int) -> Optional[str]:
    """Try fetching VIX history from yfinance using multiple ticker variants."""
    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=look_back_days)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")

    for ticker_sym in _VIX_TICKERS:
        try:
            vix = yf.Ticker(ticker_sym)
            hist = yf_retry(lambda: vix.history(start=start_str, end=end_str))

            if hist is None or hist.empty:
                logger.debug("VIX ticker %s returned empty data", ticker_sym)
                continue

            closes = hist["Close"]
            if len(closes) < 2:
                continue

            logger.info("VIX data fetched via yfinance ticker %s", ticker_sym)
            return _format_vix_report(
                closes, start_str, curr_date, source=f"yfinance ({ticker_sym})"
            )

        except Exception:
            logger.debug("VIX ticker %s failed", ticker_sym, exc_info=True)

    return None


def _vix_from_nse_api(curr_date: str) -> Optional[str]:
    """Fetch current India VIX from NSE's allIndices endpoint."""
    client = _get_nse_client()
    data = client.fetch_json(_NSE_ALL_INDICES_URL)

    if not data:
        return None

    for idx in data.get("data", []):
        idx_name = idx.get("index", "").upper()
        if "VIX" in idx_name:
            try:
                latest = float(idx.get("last", 0))
                prev_close = float(idx.get("previousClose", latest))
                open_val = float(idx.get("open", latest))
                high_val = float(idx.get("high", latest))
                low_val = float(idx.get("low", latest))
                change_pct = float(idx.get("percentChange", 0))

                mood = _interpret_vix(latest)

                report = f"""## India VIX Report (as of {curr_date})

**Source:** NSE allIndices API (current session only — no historical trend)

**Current India VIX:** {latest:.2f} ({change_pct:+.1f}% vs previous close)
**Previous Close:** {prev_close:.2f}
**Today's Range:** {low_val:.2f} – {high_val:.2f}
**Open:** {open_val:.2f}
**Market Mood:** {mood}

### ⚠️ Note
Historical trend data unavailable from yfinance. Only current session data
shown (from NSE). For historical charts, check:
- https://www.nseindia.com/market-data/india-vix

{_VIX_INTERPRETATION_GUIDE}"""
                logger.info("VIX data fetched via NSE allIndices API")
                return report

            except (ValueError, TypeError, KeyError):
                logger.warning("Failed to parse VIX from NSE allIndices", exc_info=True)

    return None


def _format_vix_report(
    closes, start_str: str, curr_date: str, source: str = "yfinance"
) -> str:
    """Format VIX closes series into a markdown report."""
    latest = closes.iloc[-1]
    prev = closes.iloc[-2] if len(closes) >= 2 else latest
    change_pct = ((latest - prev) / prev) * 100 if prev else 0
    avg = closes.mean()
    high = closes.max()
    low = closes.min()
    mood = _interpret_vix(latest)

    # Recent 5-day trend table
    recent = closes.tail(5)
    trend_lines = ""
    for date, val in recent.items():
        date_str = (
            date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)[:10]
        )
        trend_lines += f"| {date_str} | {val:.2f} |\n"

    return f"""## India VIX Report ({start_str} to {curr_date})

**Source:** {source}

**Current India VIX:** {latest:.2f} ({change_pct:+.1f}% vs previous session)
**{len(closes)}-Day Average:** {avg:.2f}
**Period Range:** {low:.2f} – {high:.2f}
**Market Mood:** {mood}

### Recent 5-Day Trend
| Date | India VIX |
|------|-----------|
{trend_lines}
{_VIX_INTERPRETATION_GUIDE}"""


def _interpret_vix(value: float) -> str:
    """Return human-readable mood for a VIX reading."""
    if value < 13:
        return "Very Low — extreme complacency, potential reversal risk"
    if value < 17:
        return "Low — market is calm, bullish bias"
    if value < 22:
        return "Moderate — normal volatility"
    if value < 30:
        return "Elevated — increased uncertainty, caution warranted"
    return "High — significant fear/uncertainty, potential capitulation"


_VIX_INTERPRETATION_GUIDE = """### Interpretation
- India VIX measures expected 30-day volatility of NIFTY 50 options.
- VIX < 15: Low fear, potentially complacent market.
- VIX 15-20: Normal range, healthy market.
- VIX > 20: Elevated fear, expect larger price swings.
- VIX > 25: High fear, possible capitulation or major event.
- Rising VIX + falling NIFTY = bearish signal (fear increasing).
- Falling VIX + rising NIFTY = bullish confirmation.
"""


# ═══════════════════════════════════════════════════════════════════════════
# FII / DII Activity
# ═══════════════════════════════════════════════════════════════════════════

def get_fii_dii_activity(
    curr_date: str,
    look_back_days: int = 10,
) -> str:
    """Fetch FII/DII cash market activity.

    **Source chain:**
    1. NSE ``/api/fiidiiTradeReact`` via curl_cffi (browser-impersonated)
    2. Graceful fallback with manual reference links

    Args:
        curr_date: Reference date in ``yyyy-mm-dd`` format.
        look_back_days: Number of sessions to report (default 10).

    Returns:
        Markdown-formatted report with buy/sell/net values and guide.
    """
    # Source 1: NSE API via curl_cffi
    report = _fii_dii_from_nse(curr_date, look_back_days)
    if report:
        return report

    return _fii_dii_fallback_message(curr_date)


def _fii_dii_from_nse(curr_date: str, look_back_days: int) -> Optional[str]:
    """Fetch FII/DII data from NSE's fiidiiTradeReact endpoint."""
    client = _get_nse_client()
    data = client.fetch_json(_NSE_FII_DII_URL)

    if not data:
        logger.info("NSE FII/DII API returned no data (expected on corporate networks)")
        return None

    # NSE returns a list of dicts with keys:
    # category, date, buyValue, sellValue, netValue
    rows = []
    for entry in data if isinstance(data, list) else []:
        rows.append({
            "category": entry.get("category", ""),
            "date": entry.get("date", ""),
            "buy": entry.get("buyValue", "N/A"),
            "sell": entry.get("sellValue", "N/A"),
            "net": entry.get("netValue", "N/A"),
        })

    if not rows:
        logger.info("NSE FII/DII response was empty or unexpected format")
        return None

    fii_rows = [
        r for r in rows
        if "FII" in r["category"].upper() or "FPI" in r["category"].upper()
    ]
    dii_rows = [r for r in rows if "DII" in r["category"].upper()]

    report = f"## FII/DII Activity Report (as of {curr_date})\n\n"
    report += "**Source:** NSE fiidiiTradeReact API\n\n"

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

    # Summary analysis
    if fii_rows and dii_rows:
        report += _fii_dii_summary(fii_rows, dii_rows)

    report += _FII_DII_INTERPRETATION_GUIDE
    logger.info("FII/DII data fetched via NSE API (%d entries)", len(rows))
    return report


def _fii_dii_summary(fii_rows: list, dii_rows: list) -> str:
    """Generate a quick summary of FII/DII net flows."""
    try:
        latest_fii_net = _parse_net(fii_rows[0].get("net"))
        latest_dii_net = _parse_net(dii_rows[0].get("net"))

        if latest_fii_net is None or latest_dii_net is None:
            return ""

        signals = []
        if latest_fii_net > 0 and latest_dii_net > 0:
            signals.append("🟢 **Both buying** — strong bullish signal")
        elif latest_fii_net < 0 and latest_dii_net < 0:
            signals.append("🔴 **Both selling** — rare, strongly bearish")
        elif latest_fii_net < 0 and latest_dii_net > 0:
            signals.append(
                "🟡 **FII selling, DII buying** — correction support pattern"
            )
        elif latest_fii_net > 0 and latest_dii_net < 0:
            signals.append(
                "🟢 **FII buying, DII selling** — foreign confidence, profit booking"
            )

        fii_label = "buying" if latest_fii_net > 0 else "selling"
        dii_label = "buying" if latest_dii_net > 0 else "selling"
        signals.append(
            f"Latest session: FII net {fii_label} ₹{abs(latest_fii_net):,.0f} Cr, "
            f"DII net {dii_label} ₹{abs(latest_dii_net):,.0f} Cr"
        )

        return "### Quick Signal\n" + "\n".join(f"- {s}" for s in signals) + "\n\n"

    except Exception:
        return ""


def _parse_net(value) -> Optional[float]:
    """Parse a net value that might be a string with commas or a number."""
    if value is None or value == "N/A":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _fii_dii_fallback_message(curr_date: str, error: str = "") -> str:
    """Return a helpful message when FII/DII data is unavailable."""
    msg = f"## FII/DII Activity Report (as of {curr_date})\n\n"
    msg += "**Data temporarily unavailable** from NSE API.\n\n"
    if error:
        msg += f"Reason: {error}\n\n"
    msg += (
        "This may be due to NSE's anti-bot protection or a weekend/holiday.\n"
        "The pipeline will continue without FII/DII signals.\n\n"
        "For manual reference, check:\n"
        "- NSE: https://www.nseindia.com/reports/fii-dii\n"
        "- Moneycontrol: https://www.moneycontrol.com/stocks/marketstats/"
        "fii_dii_activity/\n"
        "- Trendlyne: https://trendlyne.com/fii-dii-activity/\n"
    )
    return msg


_FII_DII_INTERPRETATION_GUIDE = """### Interpretation Guide
- **FII/FPI Net Positive**: Foreign investors are buying — bullish signal.
- **FII/FPI Net Negative**: Foreign investors are selling — bearish pressure.
- **DII Net Positive**: Domestic institutions buying — often contrarian to FII.
- **FII selling + DII buying**: Common during corrections; DII provides floor.
- **Both buying**: Strong bullish signal.
- **Both selling**: Rare but strongly bearish.
- Track the trend over 5-10 sessions, not single days.
"""
