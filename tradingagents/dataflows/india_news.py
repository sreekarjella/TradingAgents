"""India RSS-based news data fetching functions.

Fetches financial news from Indian sources (Economic Times, Moneycontrol,
LiveMint) via RSS feeds.  Drop-in replacement for the yfinance news functions
when the ``india_rss`` vendor is selected.

Uses ``requests`` instead of ``urllib`` so Walmart's proxy (which
requires NTLM auth) is handled transparently via environment variables.
"""

import logging
import time
from datetime import datetime, timedelta
from time import mktime
from typing import Optional
from urllib.parse import urlparse

import feedparser  # type: ignore[import-untyped]
import requests
from requests.exceptions import ConnectionError as ReqConnectionError, ProxyError

logger = logging.getLogger(__name__)

# Per-process cache of domains that returned proxy / connection errors.
# Avoids wasting ~1s per feed on retries that will never succeed within
# the same pipeline run (e.g. ET + Moneycontrol blocked by Walmart proxy).
_failed_domains: set[str] = set()

# TTL cache for fetched feed entries. The feed contents do NOT change
# per ticker, but ``get_news_india_rss`` is called once per ticker, and
# pre_screen invokes it across the whole NSE universe — a 50-ticker run
# was previously hitting each RSS URL 50 times. Cache by
# (sorted feed URL tuple, day-of-call) and re-fetch every 15 min.
_FEED_CACHE_TTL_SECS: int = 15 * 60
_feed_cache: dict[tuple, tuple[float, list[dict]]] = {}

# Audit (2026-05-15): on Walmart corp VPN, Economic Times and Moneycontrol
# RSS endpoints are firewalled — every request times out and we waste ~10s
# per feed before falling back. The 6-feed legacy default returned ZERO
# ticker-relevant articles across a 7-ticker / 7-day audit. We now keep
# only LiveMint by default (the one feed that actually responds on VPN);
# operators on open networks can re-enable ET / Moneycontrol via their
# own config if those work for them.
#
# Even on open networks LiveMint headlines rarely match individual
# tickers, so india_rss is best treated as a *macro* news source
# (get_global_news_india_rss) rather than a per-ticker workhorse.
_MARKET_FEEDS: list[str] = [
    "https://www.livemint.com/rss/markets",
]

_ECONOMY_FEEDS: list[str] = [
    "https://www.livemint.com/rss/economy",
]

_ALL_FEEDS: list[str] = _MARKET_FEEDS + _ECONOMY_FEEDS
_FEED_TIMEOUT_SECS: int = 10

# Browser-shaped UA — Moneycontrol (and a few others) return 403 to anything
# that smells like a bot. Mimicking a real Chrome string keeps them happy.
_BROWSER_UA: str = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Ticker → human-readable company name (full NIFTY 50 + JIOFIN).
# These names are used both as headline-match keywords for india_rss
# AND as the search query for google_rss. For tickers where the bare
# code matches (TCS, ITC, ONGC, NTPC) we keep the short form so Google
# returns financial coverage instead of namesakes; for ambiguous tickers
# (DRREDDY, JIOFIN, M&M) we use the full corporate name so the search
# query is unambiguous and the relevance filter has something concrete
# to match against.
_TICKER_NAME_MAP: dict[str, str] = {
    # Tier 1 — mega-caps
    "RELIANCE": "Reliance", "TCS": "TCS", "HDFCBANK": "HDFC Bank",
    "INFY": "Infosys", "ICICIBANK": "ICICI Bank", "HINDUNILVR": "Hindustan Unilever",
    "BHARTIARTL": "Bharti Airtel", "SBIN": "SBI", "BAJFINANCE": "Bajaj Finance",
    "ITC": "ITC", "KOTAKBANK": "Kotak Mahindra Bank", "LT": "Larsen Toubro",
    "AXISBANK": "Axis Bank", "HCLTECH": "HCL Tech", "WIPRO": "Wipro",
    "MARUTI": "Maruti Suzuki", "TATAMOTORS": "Tata Motors", "TATASTEEL": "Tata Steel",
    "SUNPHARMA": "Sun Pharma", "ONGC": "ONGC", "NTPC": "NTPC",
    "POWERGRID": "Power Grid", "ADANIENT": "Adani Enterprises",
    "ADANIPORTS": "Adani Ports", "ULTRACEMCO": "UltraTech Cement",
    "TECHM": "Tech Mahindra", "TITAN": "Titan Company", "ASIANPAINT": "Asian Paints",
    "NESTLEIND": "Nestle India", "JSWSTEEL": "JSW Steel",
    # Tier 2 — the rest of NIFTY 50 + ETERNAL/JIOFIN (added 2025/2026 inclusion)
    "BAJAJFINSV": "Bajaj Finserv", "BAJAJ-AUTO": "Bajaj Auto",
    "DRREDDY": "Dr Reddys Laboratories",  # Use full official name
    "CIPLA": "Cipla", "COALINDIA": "Coal India", "EICHERMOT": "Eicher Motors",
    "GRASIM": "Grasim Industries", "DIVISLAB": "Divis Laboratories",
    "APOLLOHOSP": "Apollo Hospitals", "HEROMOTOCO": "Hero MotoCorp",
    "BPCL": "BPCL", "TATACONSUM": "Tata Consumer Products",
    "BRITANNIA": "Britannia Industries", "HINDALCO": "Hindalco",
    "INDUSINDBK": "IndusInd Bank", "SBILIFE": "SBI Life Insurance",
    "HDFCLIFE": "HDFC Life Insurance", "M&M": "Mahindra Mahindra",
    "SHRIRAMFIN": "Shriram Finance", "TRENT": "Trent",
    "JIOFIN": "Jio Financial Services", "ETERNAL": "Eternal",  # parent of Zomato
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
        return urlparse(url).netloc
    except Exception:
        return url


def _fetch_entries(
    feed_urls: list[str],
    start_dt: datetime,
    end_dt: datetime,
) -> list[dict]:
    """Fetch and date-filter entries from multiple RSS feeds.

    Uses a module-level ``requests.Session`` (so HTTP_PROXY env vars are
    still honoured AND we get connection pooling) plus a 15-minute TTL
    cache keyed on (feed URL tuple, date window). Without the cache,
    pre_screen → N tickers × 6 feeds = N×6 redundant HTTP roundtrips per
    nightly run.

    Domains that fail with a connection/proxy/HTTP error are also cached
    for the lifetime of the process so subsequent calls skip them
    instantly.
    """
    cache_key = (
        tuple(sorted(feed_urls)),
        start_dt.strftime("%Y-%m-%d"),
        end_dt.strftime("%Y-%m-%d"),
    )
    cached = _feed_cache.get(cache_key)
    if cached is not None:
        ts, entries = cached
        if time.time() - ts < _FEED_CACHE_TTL_SECS:
            return entries

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
                headers={
                    "User-Agent": _BROWSER_UA,
                    "Accept": "application/rss+xml, application/xml, text/xml, */*",
                },
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
                # Drop undated articles entirely — the legacy code
                # silently included them, polluting sentiment with
                # potentially years-old archived pieces.
                if pub_date is None:
                    continue
                if not (start_dt <= pub_date <= end_dt + timedelta(days=1)):
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
            short_reason = str(exc).split("(Caused")[0].strip()[:80]
            logger.warning(
                "RSS feed blocked (%s) — will skip for this session: %s",
                _source_label(url), short_reason,
            )
        except requests.HTTPError as exc:
            _failed_domains.add(domain)
            status = getattr(exc.response, "status_code", "?")
            logger.warning(
                "RSS feed unavailable (%s): %s Client Error — caching domain for this session",
                _source_label(url), status,
            )
        except requests.RequestException as exc:
            logger.warning("RSS feed unavailable (%s): %s", _source_label(url), exc)
        except Exception:
            logger.warning("Error parsing RSS feed: %s", url, exc_info=True)

    entries.sort(key=lambda e: e.get("pub_date") or datetime.min, reverse=True)
    _feed_cache[cache_key] = (time.time(), entries)
    return entries


def _format_articles(entries: list[dict], header: str) -> str:
    """Render a list of article dicts into the expected markdown format."""
    if not entries:
        return header.rstrip(":") + " — no articles found."
    parts: list[str] = [header, ""]
    for art in entries:
        parts.append(f"### {art['title']} (source: {art['publisher']})")
        if art["summary"]:
            parts.append(art["summary"])
        if art["link"]:
            parts.append(f"Link: {art['link']}")
        parts.append("")
    return "\n".join(parts)



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
