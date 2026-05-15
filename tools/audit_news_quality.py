"""News vendor quality audit — real-data sampling across all configured sources.

Pulls live data for a representative ticker set, scores each vendor on:
  - article volume
  - recency (% within window)
  - relevance (% mentioning the company)
  - content depth (summary length distribution)
  - duplicate rate (same headline reappearing)
  - junk rate (clickbait/promo/spam patterns)
  - publisher diversity

Output: a markdown report you can act on.
"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# Bootstrap proxy + path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from tradingagents.network import configure_network
configure_network()

from tradingagents.dataflows.india_news import _fetch_entries, _MARKET_FEEDS, _ECONOMY_FEEDS, _company_name
from tradingagents.dataflows.google_news_rss import _fetch_query
from tradingagents.dataflows.yfinance_news import get_news_yfinance

# ── Test universe (mix of large/mid coverage) ────────────────────────
TEST_TICKERS = [
    "RELIANCE.NS",   # Mega-cap, tons of coverage
    "TCS.NS",         # Mega-cap IT
    "ONGC.NS",        # Mid coverage (was previously empty in india_rss)
    "SUNPHARMA.NS",   # Mid coverage (was previously empty)
    "DRREDDY.NS",     # Mid coverage
    "BHARTIARTL.NS",  # Telecom
    "JIOFIN.NS",      # Newer listing
]

END_DATE = datetime(2026, 5, 15)
START_DATE = END_DATE - timedelta(days=7)

# Junk-content fingerprints (case-insensitive substrings).
# Empirically derived from looking at typical RSS detritus.
JUNK_PATTERNS = [
    r"\bbuy\s+now\b",
    r"\bclick\s+here\b",
    r"subscribe\s+to",
    r"webinar",
    r"sponsored",
    r"advert",
    r"\b(?:join|register)\s+(?:our|now|free)\b",
    r"download\s+(?:the\s+)?app",
    r"limited\s+time\s+offer",
    r"penny\s+stock",
    r"multibagger",         # Almost always clickbait promo content
    r"100%\s+returns",
    r"guaranteed\s+returns",
    r"hot\s+stock\s+tip",
    r"f&o\s+stock\s+ideas",  # Daily promo
    r"^stocks?\s+to\s+watch",  # Generic listicles, no ticker focus
    r"^stocks?\s+to\s+buy",
    r"^top\s+\d+\s+stocks?",
]
JUNK_RX = re.compile("|".join(JUNK_PATTERNS), re.IGNORECASE)


def _has_junk(text: str) -> bool:
    return bool(JUNK_RX.search(text or ""))


def _is_relevant(text: str, ticker: str) -> bool:
    """Does the headline/summary actually mention the company?"""
    company = _company_name(ticker).lower()
    base = ticker.replace(".NS", "").replace(".BO", "").lower()
    return company in (text or "").lower() or base in (text or "").lower()


def _score_entries(entries: list[dict], ticker: str, start_dt, end_dt) -> dict:
    """Compute quality metrics over a list of article dicts."""
    if not entries:
        return {
            "count": 0,
            "in_window_pct": 0,
            "relevant_pct": 0,
            "junk_pct": 0,
            "avg_summary_len": 0,
            "publishers": [],
            "duplicate_pct": 0,
        }

    titles = [e.get("title", "") for e in entries]
    summaries = [e.get("summary", "") for e in entries]
    pub_dates = [e.get("pub_date") for e in entries]

    in_window = sum(
        1 for d in pub_dates
        if d and start_dt <= d <= end_dt + timedelta(days=1)
    )
    relevant = sum(
        1 for t, s in zip(titles, summaries)
        if _is_relevant(t, ticker) or _is_relevant(s, ticker)
    )
    junk = sum(1 for t, s in zip(titles, summaries) if _has_junk(t) or _has_junk(s))
    summary_lens = [len(s) for s in summaries if s]
    publishers = Counter(e.get("publisher", "Unknown") for e in entries)

    # Duplicate detection — normalize title (lowercase, strip punctuation)
    norm_titles = [re.sub(r"[^a-z0-9 ]", "", t.lower()) for t in titles]
    title_counts = Counter(norm_titles)
    duplicates = sum(c - 1 for c in title_counts.values() if c > 1)

    return {
        "count": len(entries),
        "in_window_pct": round(100 * in_window / len(entries), 1),
        "relevant_pct": round(100 * relevant / len(entries), 1),
        "junk_pct": round(100 * junk / len(entries), 1),
        "avg_summary_len": int(statistics.mean(summary_lens)) if summary_lens else 0,
        "publishers": publishers.most_common(5),
        "duplicate_pct": round(100 * duplicates / len(entries), 1),
        "sample_titles": titles[:3],
    }


# ── Per-feed audits ──────────────────────────────────────────────────

def audit_india_rss_per_feed(ticker: str) -> dict:
    """Audit each individual india_rss feed URL separately."""
    results = {}
    company = _company_name(ticker).lower()
    for url in _MARKET_FEEDS + _ECONOMY_FEEDS:
        entries = _fetch_entries([url], START_DATE, END_DATE)
        # Filter to ticker-relevant
        matched = [
            e for e in entries
            if company in e["title"].lower() or company in e.get("summary", "").lower()
        ]
        results[url] = _score_entries(matched, ticker, START_DATE, END_DATE)
    return results


def audit_google_rss(ticker: str) -> dict:
    company = _company_name(ticker)
    query = f"{company} stock"
    entries = _fetch_query(query, START_DATE, END_DATE)
    return _score_entries(entries, ticker, START_DATE, END_DATE)


def audit_yfinance(ticker: str) -> dict:
    """yfinance returns markdown text, not entry dicts. We have to parse it back."""
    try:
        result = get_news_yfinance(
            ticker, START_DATE.strftime("%Y-%m-%d"), END_DATE.strftime("%Y-%m-%d")
        )
        # Count "###" headers as articles
        article_count = result.count("### ")
        return {
            "count": article_count,
            "raw_chars": len(result),
            "preview": result[:300] if result else "(empty)",
        }
    except Exception as exc:
        return {"count": 0, "raw_chars": 0, "error": str(exc)}


def main():
    print(f"\n{'='*70}")
    print(f"NEWS VENDOR QUALITY AUDIT — {START_DATE.date()} to {END_DATE.date()}")
    print(f"{'='*70}\n")

    # ── Per-feed india_rss audit (aggregated across all test tickers) ──
    print("\n━━━ INDIA_RSS — Per-feed quality (aggregated across all tickers) ━━━\n")
    feed_totals: dict[str, dict] = defaultdict(lambda: {
        "total_articles": 0,
        "junk_articles": 0,
        "in_window_articles": 0,
        "summary_lens": [],
        "tickers_with_hits": 0,
    })
    for ticker in TEST_TICKERS:
        per_feed = audit_india_rss_per_feed(ticker)
        for url, m in per_feed.items():
            tot = feed_totals[url]
            tot["total_articles"] += m["count"]
            tot["junk_articles"] += int(m["count"] * m["junk_pct"] / 100)
            tot["in_window_articles"] += int(m["count"] * m["in_window_pct"] / 100)
            if m["count"] > 0:
                tot["tickers_with_hits"] += 1
            if m["avg_summary_len"]:
                tot["summary_lens"].append(m["avg_summary_len"])

    for url, t in feed_totals.items():
        avg_summary = int(statistics.mean(t["summary_lens"])) if t["summary_lens"] else 0
        coverage_pct = round(100 * t["tickers_with_hits"] / len(TEST_TICKERS), 1)
        print(f"  {url}")
        print(f"    total ticker-relevant articles: {t['total_articles']}")
        print(f"    coverage:  {t['tickers_with_hits']}/{len(TEST_TICKERS)} tickers ({coverage_pct}%)")
        print(f"    junk:      {t['junk_articles']}")
        print(f"    avg summary len: {avg_summary} chars")
        print()

    # ── google_rss per ticker ──
    print("\n━━━ GOOGLE_RSS — Per-ticker quality ━━━\n")
    google_totals = {"count": 0, "junk": 0, "relevant": 0, "duplicate": 0}
    for ticker in TEST_TICKERS:
        m = audit_google_rss(ticker)
        google_totals["count"] += m["count"]
        google_totals["junk"] += int(m["count"] * m["junk_pct"] / 100)
        google_totals["relevant"] += int(m["count"] * m["relevant_pct"] / 100)
        google_totals["duplicate"] += int(m["count"] * m["duplicate_pct"] / 100)
        pubs = ", ".join(f"{p}({c})" for p, c in m["publishers"][:3])
        print(f"  {ticker:18s} count={m['count']:3d} "
              f"in-window={m['in_window_pct']:5.1f}% "
              f"relevant={m['relevant_pct']:5.1f}% "
              f"junk={m['junk_pct']:5.1f}% "
              f"dupe={m['duplicate_pct']:5.1f}%")
        print(f"    top publishers: {pubs}")
    print(f"\n  TOTAL: {google_totals['count']} articles, "
          f"{google_totals['relevant']} relevant, "
          f"{google_totals['junk']} junk, "
          f"{google_totals['duplicate']} duplicates")

    # ── yfinance per ticker ──
    print("\n━━━ YFINANCE — Per-ticker quality ━━━\n")
    yf_totals = {"count": 0, "raw_chars": 0, "tickers_empty": 0}
    for ticker in TEST_TICKERS:
        m = audit_yfinance(ticker)
        yf_totals["count"] += m["count"]
        yf_totals["raw_chars"] += m["raw_chars"]
        if m["count"] == 0:
            yf_totals["tickers_empty"] += 1
        print(f"  {ticker:18s} count={m['count']:3d} chars={m['raw_chars']:>6,d}")
    print(f"\n  TOTAL: {yf_totals['count']} articles across {len(TEST_TICKERS)} tickers, "
          f"{yf_totals['tickers_empty']} empty")


if __name__ == "__main__":
    main()
