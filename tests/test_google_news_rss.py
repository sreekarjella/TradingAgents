"""Tests for tradingagents.dataflows.google_news_rss module.

All network calls are mocked so tests run offline (no internet needed).
"""

import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

import tradingagents.dataflows.google_news_rss as gn
from tradingagents.dataflows.google_news_rss import (
    _build_query_url,
    _fetch_query,
    _format_articles,
    _parse_pub_date,
    _publisher_label,
    get_global_news_google_rss,
    get_news_google_rss,
)


# ---------------------------------------------------------------------------
# URL building
# ---------------------------------------------------------------------------


class TestBuildQueryURL:
    def test_basic_query(self):
        url = _build_query_url("Reliance stock")
        assert "q=Reliance+stock" in url
        assert "hl=en-IN" in url
        assert "gl=IN" in url
        assert "ceid=IN:en" in url

    def test_special_chars_encoded(self):
        url = _build_query_url("M&M Auto")
        # & must be url-encoded so Google treats it as part of the query, not a param sep
        assert "M%26M" in url


class TestPublisherLabel:
    def test_dict_with_title(self):
        assert _publisher_label({"source": {"title": "Trade Brains"}}) == "Trade Brains"

    def test_string_source(self):
        assert _publisher_label({"source": "Mint"}) == "Mint"

    def test_missing_source_falls_back(self):
        assert _publisher_label({}) == "Google News"


class TestParsePubDate:
    def test_valid_struct_time(self):
        st = time.strptime("2026-05-15 10:30:00", "%Y-%m-%d %H:%M:%S")
        assert _parse_pub_date({"published_parsed": st}) == datetime(2026, 5, 15, 10, 30, 0)

    def test_missing_returns_none(self):
        assert _parse_pub_date({}) is None


# ---------------------------------------------------------------------------
# Article formatting
# ---------------------------------------------------------------------------


class TestFormatArticles:
    def test_empty_list_uses_header(self):
        out = _format_articles([], "## ONGC.NS News:")
        assert "no articles found" in out
        assert out.startswith("## ONGC.NS News")

    def test_renders_articles_with_link(self):
        arts = [{
            "title": "ONGC posts profit",
            "summary": "Strong quarter.",
            "link": "https://example.com/ongc",
            "publisher": "Trade Brains",
            "pub_date": datetime(2026, 5, 15),
        }]
        out = _format_articles(arts, "## Header:")
        assert "### ONGC posts profit (source: Trade Brains)" in out
        assert "Strong quarter." in out
        assert "Link: https://example.com/ongc" in out

    def test_skips_empty_summary_and_link(self):
        arts = [{
            "title": "Bare headline",
            "summary": "",
            "link": "",
            "publisher": "Google News",
            "pub_date": datetime(2026, 5, 15),
        }]
        out = _format_articles(arts, "## Header:")
        assert "### Bare headline" in out
        assert "Link:" not in out


# ---------------------------------------------------------------------------
# _fetch_query — network mocking
# ---------------------------------------------------------------------------


def _make_feedparser_result(entries):
    """Build a mock object that quacks like feedparser.parse(...) output."""
    result = MagicMock()
    result.bozo = False
    result.entries = entries
    return result


def _entry(title, days_ago_from=datetime(2026, 5, 15), summary="", link="https://x", source="Mint"):
    """Build a feedparser-style entry dict."""
    return {
        "title": title,
        "summary": summary,
        "link": link,
        "source": source,
        "published_parsed": days_ago_from.timetuple(),
    }


class TestFetchQuery:
    def setup_method(self):
        # Reset module-level caches between tests so they're hermetic.
        gn._feed_cache.clear()
        gn._failed_domains.clear()

    def test_returns_dated_entries_in_window(self):
        entries = [
            _entry("Latest", datetime(2026, 5, 14)),
            _entry("Earliest", datetime(2026, 5, 9)),
        ]
        with patch.object(gn, "requests") as mock_requests, \
             patch.object(gn, "feedparser") as mock_feedparser:
            mock_requests.get.return_value.content = b"<rss/>"
            mock_requests.get.return_value.raise_for_status = MagicMock()
            mock_feedparser.parse.return_value = _make_feedparser_result(entries)

            out = _fetch_query("Reliance stock", datetime(2026, 5, 8), datetime(2026, 5, 15))

        assert len(out) == 2
        # Newest first
        assert out[0]["title"] == "Latest"

    def test_drops_undated_entries(self):
        entries = [
            _entry("Dated", datetime(2026, 5, 14)),
            {"title": "Undated", "summary": "", "link": "", "source": "X"},  # no published_parsed
        ]
        with patch.object(gn, "requests") as mock_requests, \
             patch.object(gn, "feedparser") as mock_feedparser:
            mock_requests.get.return_value.content = b"<rss/>"
            mock_requests.get.return_value.raise_for_status = MagicMock()
            mock_feedparser.parse.return_value = _make_feedparser_result(entries)

            out = _fetch_query("Q", datetime(2026, 5, 8), datetime(2026, 5, 15))

        titles = [e["title"] for e in out]
        assert "Dated" in titles
        assert "Undated" not in titles

    def test_dedupes_by_title(self):
        entries = [
            _entry("Same", datetime(2026, 5, 14)),
            _entry("Same", datetime(2026, 5, 13)),
        ]
        with patch.object(gn, "requests") as mock_requests, \
             patch.object(gn, "feedparser") as mock_feedparser:
            mock_requests.get.return_value.content = b"<rss/>"
            mock_requests.get.return_value.raise_for_status = MagicMock()
            mock_feedparser.parse.return_value = _make_feedparser_result(entries)

            out = _fetch_query("Q", datetime(2026, 5, 8), datetime(2026, 5, 15))

        assert len(out) == 1

    def test_filters_outside_date_window(self):
        entries = [
            _entry("InWindow", datetime(2026, 5, 14)),
            _entry("TooOld", datetime(2026, 4, 1)),
            _entry("TooNew", datetime(2026, 6, 1)),
        ]
        with patch.object(gn, "requests") as mock_requests, \
             patch.object(gn, "feedparser") as mock_feedparser:
            mock_requests.get.return_value.content = b"<rss/>"
            mock_requests.get.return_value.raise_for_status = MagicMock()
            mock_feedparser.parse.return_value = _make_feedparser_result(entries)

            out = _fetch_query("Q", datetime(2026, 5, 8), datetime(2026, 5, 15))

        titles = [e["title"] for e in out]
        assert titles == ["InWindow"]

    def test_caches_within_ttl(self):
        entries = [_entry("Cached", datetime(2026, 5, 14))]
        with patch.object(gn, "requests") as mock_requests, \
             patch.object(gn, "feedparser") as mock_feedparser:
            mock_requests.get.return_value.content = b"<rss/>"
            mock_requests.get.return_value.raise_for_status = MagicMock()
            mock_feedparser.parse.return_value = _make_feedparser_result(entries)

            _fetch_query("Q", datetime(2026, 5, 8), datetime(2026, 5, 15))
            _fetch_query("Q", datetime(2026, 5, 8), datetime(2026, 5, 15))

            # Second call should hit cache, not network
            assert mock_requests.get.call_count == 1

    def test_remembers_failed_domain(self):
        from requests.exceptions import ConnectionError as ReqConnectionError
        with patch.object(gn, "requests") as mock_requests:
            mock_requests.get.side_effect = ReqConnectionError("blocked")
            mock_requests.exceptions = __import__("requests").exceptions

            out1 = _fetch_query("Q1", datetime(2026, 5, 8), datetime(2026, 5, 15))
            out2 = _fetch_query("Q2", datetime(2026, 5, 8), datetime(2026, 5, 15))

        assert out1 == [] and out2 == []
        # First call hits network and fails; second short-circuits via _failed_domains
        assert mock_requests.get.call_count == 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class TestGetNewsGoogleRSS:
    def setup_method(self):
        gn._feed_cache.clear()
        gn._failed_domains.clear()

    def test_invalid_date_returns_error_string(self):
        out = get_news_google_rss("ONGC.NS", "bad", "2026-05-15")
        assert "Invalid date format" in out

    def test_returns_no_articles_message_when_empty(self):
        with patch.object(gn, "_fetch_query", return_value=[]):
            out = get_news_google_rss("ONGC.NS", "2026-05-08", "2026-05-15")
        assert "No Google News found for ONGC.NS" in out

    def test_caps_at_per_ticker_limit(self):
        # Generate way more than the limit — titles must mention the ticker so
        # they survive the new relevance filter (otherwise they'd be dropped).
        many = [{
            "title": f"ONGC quarterly update #{i}",
            "summary": "",
            "link": "",
            "publisher": "Mint",
            "pub_date": datetime(2026, 5, 14),
        } for i in range(100)]
        with patch.object(gn, "_fetch_query", return_value=many):
            out = get_news_google_rss("ONGC.NS", "2026-05-08", "2026-05-15")

        # Only the cap's worth of "###" article markers
        assert out.count("### ONGC") == gn._PER_TICKER_ARTICLE_LIMIT

    def test_relevance_filter_drops_off_topic_articles(self):
        """Google occasionally returns sector pieces that don't name the company."""
        mixed = [
            {  # On-topic — mentions ONGC
                "title": "ONGC wins pipeline contract",
                "summary": "", "link": "", "publisher": "Mint",
                "pub_date": datetime(2026, 5, 14),
            },
            {  # Off-topic — generic sector piece, no ticker mention
                "title": "Indian energy sector outlook for 2026",
                "summary": "Macro view of oil and gas demand.",
                "link": "", "publisher": "ET",
                "pub_date": datetime(2026, 5, 13),
            },
        ]
        with patch.object(gn, "_fetch_query", return_value=mixed):
            out = get_news_google_rss("ONGC.NS", "2026-05-08", "2026-05-15")

        assert "ONGC wins pipeline contract" in out
        assert "Indian energy sector outlook" not in out

    def test_junk_filter_drops_promo_content(self):
        """Multibagger / paid-tip / penny-stock spam must never reach the LLM."""
        mixed = [
            {  # Legit
                "title": "ONGC Q4 results beat estimates",
                "summary": "", "link": "", "publisher": "Mint",
                "pub_date": datetime(2026, 5, 14),
            },
            {  # Junk — multibagger clickbait
                "title": "ONGC: This multibagger penny stock could 10x your money",
                "summary": "", "link": "", "publisher": "random.tips",
                "pub_date": datetime(2026, 5, 14),
            },
            {  # Junk — sure-shot tip spam
                "title": "ONGC sure-shot tip with guaranteed returns",
                "summary": "", "link": "", "publisher": "random.tips",
                "pub_date": datetime(2026, 5, 14),
            },
        ]
        with patch.object(gn, "_fetch_query", return_value=mixed):
            out = get_news_google_rss("ONGC.NS", "2026-05-08", "2026-05-15")

        assert "ONGC Q4 results beat estimates" in out
        assert "multibagger" not in out
        assert "sure-shot" not in out

    def test_listicles_kept_when_ticker_mentioned(self):
        """‘Stocks to Watch Today’ daily roundups are intentionally NOT junked—
        they often surface why a stock is in focus and the relevance filter
        already keeps them tied to the actual ticker."""
        listicle = [{
            "title": "Stocks to Watch Today: Bharti Airtel, HAL, Tata Motors and more",
            "summary": "", "link": "", "publisher": "Mint",
            "pub_date": datetime(2026, 5, 14),
        }]
        with patch.object(gn, "_fetch_query", return_value=listicle):
            out = get_news_google_rss("BHARTIARTL.NS", "2026-05-08", "2026-05-15")

        assert "Stocks to Watch" in out


class TestGetGlobalNewsGoogleRSS:
    def test_invalid_date_returns_error_string(self):
        out = get_global_news_google_rss("not-a-date")
        assert "Invalid date format" in out

    def test_respects_limit(self):
        many = [{
            "title": f"Macro {i}",
            "summary": "",
            "link": "",
            "publisher": "Mint",
            "pub_date": datetime(2026, 5, 14),
        } for i in range(50)]
        with patch.object(gn, "_fetch_query", return_value=many):
            out = get_global_news_google_rss("2026-05-15", look_back_days=7, limit=5)

        assert out.count("### Macro") == 5
