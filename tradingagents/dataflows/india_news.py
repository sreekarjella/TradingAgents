"""India RSS-based news data fetching functions.

Fetches financial news from Indian sources (Economic Times, Moneycontrol,
LiveMint) via RSS feeds.  Drop-in replacement for the yfinance news functions
when the ``india_rss`` vendor is selected.

Uses ``requests`` instead of ``urllib`` so Walmart's proxy (which
requires NTLM auth) is handled transparently via environment variables.
"""

import logging
from datetime import datetime, timedelta
from time import mktime
from typing import Optional

import feedparser  # type: ignore[import-untyped]
import requests
from requests.exceptions import ConnectionError as ReqConnectionError, ProxyError

logger = logging.getLogger(__name__)

# Per-process cache of domains that returned proxy / connection errors.
# Avoids wasting ~1s per feed on retries that will never succeed within
# the same pipeline run (e.g. ET + Moneycontrol blocked by Walmart proxy).
_failed_domains: set[str] = set()

_MARKET_FEEDS: list[str] = [
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.moneycontrol.com/rss/marketreports.xml",
    "https://www.livemint.com/rss/markets",
]

_ECONOMY_FEEDS: list[str] = [
    "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms",
    "https://www.moneycontrol.com/rss/business.xml",
    "https://www.livemint.com/rss/economy",
]

_ALL_FEEDS: list[str] = _MARKET_FEEDS + _ECONOMY_FEEDS
_FEED_TIMEOUT_SECS: int = 10

# Ticker → human-readable company name (top NSE/BSE stocks)
_TICKER_NAME_MAP: dict[str, str] = {
    "RELIANCE": "Reliance", "TCS": "TCS", "HDFCBANK": "HDFC Bank",
    "INFY": "Infosys", "ICICIBANK": "ICICI Bank", "HINDUNILVR": "Hindustan Unilever",
    "BHARTIARTL": "Bharti Airtel", "SBIN": "SBI", "BAJFINANCE": "Bajaj Finance",
    "ITC": "ITC", "KOTAKBANK": "Kotak Mahindra Bank", "LT": "L&T",
    "AXISBANK": "Axis Bank", "HCLTECH": "HCL Tech", "WIPRO": "Wipro",
    "MARUTI": "Maruti Suzuki", "TATAMOTORS": "Tata Motors", "TATASTEEL": "Tata Steel",
    "SUNPHARMA": "Sun Pharma", "ONGC": "ONGC", "NTPC": "NTPC",
    "POWERGRID": "Power Grid", "ADANIENT": "Adani Enterprises",
    "ADANIPORTS": "Adani Ports", "ULTRACEMCO": "UltraTech Cement",
    "TECHM": "Tech Mahindra", "TITAN": "Titan", "ASIANPAINT": "Asian Paints",
    "NESTLEIND": "Nestle India", "JSWSTEEL": "JSW Steel",
}


def _strip_suffix(ticker: str) -> str:
    """Remove ``.NS`` / ``.BO`` exchange suffix from an Indian ticker."""
    for suffix in (".NS", ".BO"):
        if ticker.upper().endswith(suffix):
            return ticker[: -len(suffix)]
    return ticker


def _company_name(ticker: str) -> str:
    """Return a human-friendly search term for *ticker*."""
    base = _strip_suffix(ticker).upper()
    return _TICKER_NAME_MAP.get(base, base.replace("_", " ").title())


def _parse_pub_date(entry: dict) -> Optional[datetime]:
    """Extract a naive ``datetime`` from a feedparser entry."""
    pp = entry.get("published_parsed")
    if pp:
        try:
            return datetime.fromtimestamp(mktime(pp))
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _source_label(feed_url: str) -> str:
    """Derive a short publisher name from the feed URL."""
    if "economictimes" in feed_url:
        return "Economic Times"
    if "moneycontrol" in feed_url:
        return "Moneycontrol"
    if "livemint" in feed_url:
        return "LiveMint"
    return "Unknown"


def _extract_domain(url: str) -> str:
    """Extract domain from a feed URL for failure tracking."""
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc
    except Exception:
        return url


def _fetch_entries(
    feed_urls: list[str],
    start_dt: datetime,
    end_dt: datetime,
) -> list[dict]:
    """Fetch and date-filter entries from multiple RSS feeds.

    Uses ``requests.get`` so the ``HTTP_PROXY`` / ``HTTPS_PROXY``
    environment variables set by ``network.configure_network()`` are
    picked up automatically — unlike ``urllib.request`` which fails
    with a 407 on the Walmart proxy.

    Domains that fail with a connection/proxy error are cached for the
    lifetime of the process so subsequent calls skip them instantly.
    """
    entries: list[dict] = []
    seen_titles: set[str] = set()

    for url in feed_urls:
        domain = _extract_domain(url)
        if domain in _failed_domains:
            logger.debug("Skipping previously-failed domain: %s", domain)
            continue

        try:
            resp = requests.get(
                url,
                headers={"User-Agent": "TradingAgents/1.0"},
                timeout=_FEED_TIMEOUT_SECS,
            )
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            if feed.bozo and not feed.entries:
                logger.warning("RSS feed returned no entries: %s", url)
                continue
            source = _source_label(url)
            for entry in feed.entries:
                title = entry.get("title", "").strip()
                if not title or title in seen_titles:
                    continue
                pub_date = _parse_pub_date(entry)
                if pub_date and not (start_dt <= pub_date <= end_dt + timedelta(days=1)):
                    continue
                seen_titles.add(title)
                entries.append({
                    "title": title,
                    "summary": entry.get("summary", "").strip(),
                    "link": entry.get("link", ""),
                    "publisher": source,
                    "pub_date": pub_date,
                })
        except (ReqConnectionError, ProxyError) as exc:
            _failed_domains.add(domain)
            # Truncate the exception — the full ProxyError trace is ~300 chars
            # of nested wrappers that don't tell the user anything new beyond
            # "this domain is blocked". Cap at 80 chars for log hygiene.
            short_reason = str(exc).split("(Caused")[0].strip()[:80]
            logger.warning(
                "RSS feed blocked (%s) — will skip for this session: %s",
                _source_label(url), short_reason,
            )
        except requests.RequestException as exc:
            logger.warning("RSS feed unavailable (%s): %s", _source_label(url), exc)
        except Exception:
            logger.warning("Error parsing RSS feed: %s", url, exc_info=True)

    entries.sort(key=lambda e: e.get("pub_date") or datetime.min, reverse=True)
    return entries


def _format_articles(entries: list[dict], header: str) -> str:
    """Render a list of article dicts into the expected markdown format."""
    if not entries:
        return header.rstrip(":") + " — no articles found."
    body = ""
    for art in entries:
        body += f"### {art['title']} (source: {art['publisher']})\n"
        if art["summary"]:
            body += f"{art['summary']}\n"
        if art["link"]:
            body += f"Link: {art['link']}\n"
        body += "\n"
    return f"{header}\n\n{body}"



def get_news_india_rss(
    ticker: str,
    start_date: str,
    end_date: str,
) -> str:
    """Fetch ticker-specific news from Indian RSS feeds."""
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError as exc:
        return f"Invalid date format: {exc}"

    search_term = _company_name(ticker).lower()
    entries = _fetch_entries(_ALL_FEEDS, start_dt, end_dt)

    matched = [
        e for e in entries
        if search_term in e["title"].lower() or search_term in e["summary"].lower()
    ]

    header = f"## {ticker} News from Indian Sources, from {start_date} to {end_date}:"
    if not matched:
        return f"No Indian news found for {ticker} between {start_date} and {end_date}"
    return _format_articles(matched, header)


def get_global_news_india_rss(
    curr_date: str,
    look_back_days: int = 7,
    limit: int = 10,
) -> str:
    """Fetch India macro / global news from Indian RSS feeds."""
    try:
        end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    except ValueError as exc:
        return f"Invalid date format: {exc}"

    start_dt = end_dt - timedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")

    entries = _fetch_entries(_ECONOMY_FEEDS + _MARKET_FEEDS, start_dt, end_dt)
    entries = entries[:limit]

    header = f"## India Market & Economy News, from {start_date} to {curr_date}:"
    return _format_articles(entries, header)
