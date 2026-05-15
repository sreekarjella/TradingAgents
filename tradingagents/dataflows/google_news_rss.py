"""Google News RSS — keyless per-ticker news fallback for thinly-covered stocks.

Why this module exists
----------------------
The ``india_rss`` vendor only catches stories that the three Indian financial
RSS feeds (ET / Moneycontrol / LiveMint) actually publish.  For mid-caps and
sector-specific names like ONGC, SUNPHARMA, BHARTIARTL, those feeds frequently
return zero hits in a 7-day window.  Yahoo Finance news for ``.NS`` tickers is
similarly patchy.  Alpha Vantage returns a tiny "no items" envelope for non-US
symbols.  Result: the LLM analyses these stocks *blind*.

Google News exposes a free, keyless RSS endpoint that lets us search any
phrase — including the company name — across the entire web of news
publishers.  No signup, no rate limit, no API key. The ``hl=en-IN`` and
``gl=IN`` query params bias results toward Indian publications.

Drop-in replacement for the other ``get_news_*`` / ``get_global_news_*``
functions in the vendor table.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from time import mktime
from typing import Optional
from urllib.parse import quote_plus, urlparse

import feedparser  # type: ignore[import-untyped]
import requests
from requests.exceptions import ConnectionError as ReqConnectionError, ProxyError

from .india_news import _company_name, _strip_suffix  # reuse the same ticker → name mapping

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────
_GOOGLE_NEWS_BASE: str = "https://news.google.com/rss/search"
_FEED_TIMEOUT_SECS: int = 10
_BROWSER_UA: str = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Per-ticker hard cap on returned articles. Google News can return
# hundreds of items for popular tickers (Bharti Airtel: ~80, Reliance: ~100+);
# unbounded payloads inflate the LLM context window dramatically. Newest-first
# means the cap keeps the *most recent* coverage.
_PER_TICKER_ARTICLE_LIMIT: int = 25

# Per-process cache keyed by (query, start, end). Same justification as
# india_news._feed_cache: pre_screen + pipeline can hit the same query
# repeatedly within one nightly run.
_FEED_CACHE_TTL_SECS: int = 15 * 60
_feed_cache: dict[tuple, tuple[float, list[dict]]] = {}

# Domains that have proven unreachable (proxy block, DNS, etc.) get
# remembered for the lifetime of the process so we don't keep paying
# the timeout cost on every call.
_failed_domains: set[str] = set()

# ── Quality filters ──────────────────────────────────────────────
# Patterns derived from the 2026-05-15 audit: titles matching these are
# either pure promo / paid content, illegal Indian "sure-shot tip"
# spam, or generic clickbait that contributes zero signal to a trading
# decision. Listicles like "Stocks to Watch Today" are intentionally
# NOT junk-listed because they often surface the actual reason a stock
# is in focus that morning — the relevance filter already keeps them
# tethered to the target ticker.
_JUNK_PATTERNS = [
    r"\bbuy\s+now\b", r"\bclick\s+here\b", r"subscribe\s+to",
    r"\bwebinar\b", r"\bsponsored\b", r"\badvert",
    r"\b(?:join|register)\s+(?:our|now|free)\b",
    r"download\s+(?:the\s+)?app", r"limited\s+time\s+offer",
    r"\bpenny\s+stock\b", r"\bmultibagger\b",
    r"100%\s+returns", r"guaranteed\s+returns",
    r"hot\s+stock\s+tip", r"sure[\s-]?shot",
]
_JUNK_RX = re.compile("|".join(_JUNK_PATTERNS), re.IGNORECASE)


def _is_junk(text: str) -> bool:
    """Return True when *text* matches any known clickbait / promo pattern."""
    return bool(text) and bool(_JUNK_RX.search(text))


def _is_relevant(article: dict, ticker: str) -> bool:
    """Does the article actually mention the company in title or summary?

    Google's RSS search is fuzzy and occasionally returns tangentially
    related results (e.g. ``Dr Reddy stock`` once returned a generic
    pharma index piece that never named the company). We require the
    company name OR the bare ticker code to appear somewhere in the
    title or summary so the LLM never sees off-topic articles.
    """
    haystack = (article.get("title", "") + " " + article.get("summary", "")).lower()
    if not haystack.strip():
        return False
    name_tokens = _company_name(ticker).lower().split()
    bare = _strip_suffix(ticker).lower()
    # Match if the bare ticker appears OR the FIRST distinctive name
    # token appears (covers "Dr Reddys", "Dr Reddy's" and "Dr Reddy"
    # without forcing exact-string equality).
    if bare in haystack:
        return True
    if name_tokens and name_tokens[0] in haystack:
        return True
    return False


# ── Internal helpers ───────────────────────────────────────────────────

def _build_query_url(query: str, region: str = "IN") -> str:
    """Construct a Google News RSS URL for *query* biased to *region*.

    ``hl`` controls the UI language, ``gl`` the geographic region, ``ceid``
    the country edition.  Together they make Google return India-localised
    results without us having to sniff the user's locale.
    """
    return (
        f"{_GOOGLE_NEWS_BASE}?q={quote_plus(query)}"
        f"&hl=en-{region}&gl={region}&ceid={region}:en"
    )


def _parse_pub_date(entry: dict) -> Optional[datetime]:
    """Extract a naive ``datetime`` from a feedparser entry, if available."""
    pp = entry.get("published_parsed")
    if pp:
        try:
            return datetime.fromtimestamp(mktime(pp))
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _publisher_label(entry: dict) -> str:
    """Pull the source publisher name from a Google News RSS entry."""
    source = entry.get("source")
    if isinstance(source, dict):
        return source.get("title", "Google News")
    if isinstance(source, str) and source:
        return source
    return "Google News"


def _fetch_query(query: str, start_dt: datetime, end_dt: datetime) -> list[dict]:
    """Hit the Google News RSS endpoint for *query* and return date-filtered entries."""
    cache_key = (query, start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
    cached = _feed_cache.get(cache_key)
    if cached is not None:
        ts, entries = cached
        if time.time() - ts < _FEED_CACHE_TTL_SECS:
            return entries

    url = _build_query_url(query)
    domain = urlparse(url).netloc
    if domain in _failed_domains:
        logger.debug("Skipping previously-failed domain: %s", domain)
        return []

    entries: list[dict] = []
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
            logger.warning("Google News RSS returned no entries for query: %s", query)
            return []

        seen_titles: set[str] = set()
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            if not title or title in seen_titles:
                continue
            pub_date = _parse_pub_date(entry)
            # Drop undated articles — Google News occasionally returns
            # archived items with no published_parsed; without a date we
            # can't honour the requested window.
            if pub_date is None:
                continue
            if not (start_dt <= pub_date <= end_dt + timedelta(days=1)):
                continue
            seen_titles.add(title)
            entries.append({
                "title": title,
                "summary": entry.get("summary", "").strip(),
                "link": entry.get("link", ""),
                "publisher": _publisher_label(entry),
                "pub_date": pub_date,
            })
    except (ReqConnectionError, ProxyError) as exc:
        _failed_domains.add(domain)
        short_reason = str(exc).split("(Caused")[0].strip()[:80]
        logger.warning(
            "Google News RSS blocked — caching for this session: %s",
            short_reason,
        )
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", "?")
        # 4xx/5xx from Google itself is rare but worth surfacing
        logger.warning("Google News RSS returned HTTP %s for query: %s", status, query)
    except requests.RequestException as exc:
        logger.warning("Google News RSS request failed: %s", exc)
    except Exception:
        logger.warning("Error parsing Google News RSS for query: %s", query, exc_info=True)

    entries.sort(key=lambda e: e.get("pub_date") or datetime.min, reverse=True)
    _feed_cache[cache_key] = (time.time(), entries)
    return entries


def _format_articles(entries: list[dict], header: str) -> str:
    """Render a list of article dicts into the standard markdown layout."""
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


# ── Public API ─────────────────────────────────────────────────────────

def get_news_google_rss(ticker: str, start_date: str, end_date: str) -> str:
    """Fetch ticker-specific news via Google News RSS.

    The query combines the company's display name with the literal word
    ``stock`` so we bias toward financial coverage rather than corporate
    PR / unrelated namesakes (e.g. ``Reliance`` the brand vs. Reliance
    Industries the ticker).
    """
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError as exc:
        return f"Invalid date format: {exc}"

    company = _company_name(ticker)
    query = f"{company} stock"
    raw_entries = _fetch_query(query, start_dt, end_dt)

    # ── Quality filtering ────────────────────────────────────────
    # 1) Drop articles that don't actually mention the company anywhere
    #    (Google's fuzzy search occasionally returns sector/index pieces).
    # 2) Drop pure promo / multibagger / paid-tip junk.
    # 3) Cap to the newest N to keep the LLM context bounded.
    relevant = [e for e in raw_entries if _is_relevant(e, ticker)]
    clean = [e for e in relevant if not (_is_junk(e.get("title", "")) or _is_junk(e.get("summary", "")))]
    entries = clean[:_PER_TICKER_ARTICLE_LIMIT]

    if raw_entries:
        logger.info(
            "google_rss[%s]: %d raw → %d relevant → %d after junk filter → %d kept (cap %d)",
            ticker, len(raw_entries), len(relevant), len(clean), len(entries),
            _PER_TICKER_ARTICLE_LIMIT,
        )

    header = f"## {ticker} News from Google News, from {start_date} to {end_date}:"
    if not entries:
        return f"No Google News found for {ticker} between {start_date} and {end_date}"
    return _format_articles(entries, header)


def get_global_news_google_rss(
    curr_date: str,
    look_back_days: int = 7,
    limit: int = 10,
) -> str:
    """Fetch India macro / market news via Google News RSS."""
    try:
        end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    except ValueError as exc:
        return f"Invalid date format: {exc}"

    start_dt = end_dt - timedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")

    # A single broad India-market query — Google's relevance ranking
    # already prioritises recent / high-signal financial coverage.
    entries = _fetch_query("India stock market NSE BSE economy", start_dt, end_dt)
    entries = entries[:limit]

    header = f"## India Market & Economy News (Google News), from {start_date} to {curr_date}:"
    return _format_articles(entries, header)
