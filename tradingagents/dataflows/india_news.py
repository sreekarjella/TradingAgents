"""India RSS-based news data fetching functions.

Fetches financial news from Indian sources (Economic Times, Moneycontrol,
LiveMint) via RSS feeds.  Drop-in replacement for the yfinance news functions
when the ``india_rss`` vendor is selected.
"""

import logging
from datetime import datetime, timedelta
from time import mktime
from typing import Optional
from urllib.request import Request, urlopen

import feedparser  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

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


def _fetch_entries(
    feed_urls: list[str],
    start_dt: datetime,
    end_dt: datetime,
) -> list[dict]:
    """Fetch and date-filter entries from multiple RSS feeds."""
    entries: list[dict] = []
    seen_titles: set[str] = set()

    for url in feed_urls:
        try:
            req = Request(url, headers={"User-Agent": "TradingAgents/1.0"})
            with urlopen(req, timeout=_FEED_TIMEOUT_SECS) as resp:
                raw = resp.read()
            feed = feedparser.parse(raw)
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
        except Exception:
            logger.exception("Error fetching RSS feed: %s", url)

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
