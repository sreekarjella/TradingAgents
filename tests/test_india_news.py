"""Tests for tradingagents.dataflows.india_news module.

All network calls are mocked so tests run offline (no VPN needed).
"""

import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dataflows.india_news import (
    _company_name,
    _fetch_entries,
    _format_articles,
    _parse_pub_date,
    _source_label,
    _strip_suffix,
    get_global_news_india_rss,
    get_news_india_rss,
)


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestStripSuffix:
    def test_removes_ns(self):
        assert _strip_suffix("RELIANCE.NS") == "RELIANCE"

    def test_removes_bo(self):
        assert _strip_suffix("TCS.BO") == "TCS"

    def test_case_insensitive(self):
        assert _strip_suffix("infy.ns") == "infy"

    def test_no_suffix(self):
        assert _strip_suffix("AAPL") == "AAPL"

    def test_other_suffix_unchanged(self):
        assert _strip_suffix("VOD.L") == "VOD.L"


class TestCompanyName:
    def test_mapped_ticker(self):
        assert _company_name("HDFCBANK.NS") == "HDFC Bank"
        assert _company_name("BHARTIARTL.BO") == "Bharti Airtel"
        assert _company_name("HINDUNILVR.NS") == "Hindustan Unilever"

    def test_unmapped_ticker_titlecased(self):
        assert _company_name("NEWSTOCK.NS") == "Newstock"

    def test_bare_ticker(self):
        assert _company_name("RELIANCE") == "Reliance"


class TestSourceLabel:
    @pytest.mark.parametrize("url,expected", [
        ("https://economictimes.indiatimes.com/foo", "Economic Times"),
        ("https://www.moneycontrol.com/rss/business.xml", "Moneycontrol"),
        ("https://www.livemint.com/rss/economy", "LiveMint"),
        ("https://example.com/feed", "Unknown"),
    ])
    def test_labels(self, url: str, expected: str):
        assert _source_label(url) == expected


class TestParsePubDate:
    def test_valid_struct_time(self):
        entry = {"published_parsed": time.strptime("2026-05-01", "%Y-%m-%d")}
        result = _parse_pub_date(entry)
        assert result is not None
        assert result.year == 2026 and result.month == 5 and result.day == 1

    def test_missing_returns_none(self):
        assert _parse_pub_date({}) is None
        assert _parse_pub_date({"published_parsed": None}) is None


class TestFormatArticles:
    def test_renders_markdown(self):
        articles = [
            {
                "title": "Markets Rally",
                "publisher": "Economic Times",
                "summary": "Sensex rose 500 pts.",
                "link": "https://example.com/1",
            }
        ]
        result = _format_articles(articles, "## Header:")
        assert "## Header:" in result
        assert "### Markets Rally (source: Economic Times)" in result
        assert "Sensex rose 500 pts." in result
        assert "Link: https://example.com/1" in result

    def test_empty_list(self):
        result = _format_articles([], "## Header:")
        assert "no articles found" in result

    def test_no_summary_or_link(self):
        articles = [{"title": "T", "publisher": "P", "summary": "", "link": ""}]
        result = _format_articles(articles, "## H:")
        assert "### T (source: P)" in result
        assert "Link:" not in result


# ---------------------------------------------------------------------------
# Mocked integration tests
# ---------------------------------------------------------------------------

_SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Reliance posts record Q4 profit</title>
      <link>https://example.com/reliance</link>
      <description>Reliance Industries reported record quarterly profit.</description>
      <pubDate>Thu, 08 May 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>India GDP growth accelerates</title>
      <link>https://example.com/gdp</link>
      <description>India GDP grew 7.5% in Q1.</description>
      <pubDate>Wed, 07 May 2026 09:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Old article from 2024</title>
      <link>https://example.com/old</link>
      <description>This is ancient.</description>
      <pubDate>Mon, 01 Jan 2024 09:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""


def _mock_requests_get(url, headers=None, timeout=10):
    """Return a mock ``requests.Response`` that yields our sample RSS."""
    mock_resp = MagicMock()
    mock_resp.content = _SAMPLE_RSS
    mock_resp.text = _SAMPLE_RSS.decode("utf-8")
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock(return_value=None)
    return mock_resp


# `india_news` caches failed domains in a module-level set, so clear it
# between tests to avoid one test's failure poisoning subsequent runs.
@pytest.fixture(autouse=True)
def _reset_failed_domains():
    from tradingagents.dataflows import india_news as _mod
    _mod._failed_domains.clear()
    yield
    _mod._failed_domains.clear()


@pytest.mark.unit
class TestFetchEntries:
    @patch("tradingagents.dataflows.india_news.requests.get", side_effect=_mock_requests_get)
    def test_date_filtering(self, mock_get):
        start = datetime(2026, 5, 1)
        end = datetime(2026, 5, 9)
        entries = _fetch_entries(["https://economictimes.indiatimes.com/feed"], start, end)
        titles = [e["title"] for e in entries]
        assert "Reliance posts record Q4 profit" in titles
        assert "India GDP growth accelerates" in titles
        assert "Old article from 2024" not in titles

    @patch("tradingagents.dataflows.india_news.requests.get", side_effect=_mock_requests_get)
    def test_deduplication(self, mock_get):
        start = datetime(2026, 5, 1)
        end = datetime(2026, 5, 9)
        # Same feed URL twice — should still deduplicate
        entries = _fetch_entries(
            ["https://economictimes.indiatimes.com/a", "https://economictimes.indiatimes.com/b"],
            start, end,
        )
        titles = [e["title"] for e in entries]
        assert titles.count("Reliance posts record Q4 profit") == 1

    @patch(
        "tradingagents.dataflows.india_news.requests.get",
        side_effect=__import__("requests").exceptions.ConnectionError("DNS fail"),
    )
    def test_handles_network_error(self, mock_get):
        entries = _fetch_entries(["https://bad.url"], datetime(2026, 5, 1), datetime(2026, 5, 9))
        assert entries == []


@pytest.mark.unit
class TestGetNewsIndiaRSS:
    @patch("tradingagents.dataflows.india_news.requests.get", side_effect=_mock_requests_get)
    def test_finds_ticker_news(self, mock_get):
        result = get_news_india_rss("RELIANCE.NS", "2026-05-01", "2026-05-09")
        assert "RELIANCE.NS" in result
        assert "Reliance posts record Q4 profit" in result
        assert "India GDP growth accelerates" not in result  # not about Reliance

    @patch("tradingagents.dataflows.india_news.requests.get", side_effect=_mock_requests_get)
    def test_no_match(self, mock_get):
        result = get_news_india_rss("WIPRO.NS", "2026-05-01", "2026-05-09")
        assert "No Indian news found for WIPRO.NS" in result

    def test_invalid_date(self):
        result = get_news_india_rss("RELIANCE.NS", "not-a-date", "2026-05-09")
        assert "Invalid date format" in result


@pytest.mark.unit
class TestGetGlobalNewsIndiaRSS:
    @patch("tradingagents.dataflows.india_news.requests.get", side_effect=_mock_requests_get)
    def test_returns_articles(self, mock_get):
        result = get_global_news_india_rss("2026-05-09", look_back_days=14, limit=10)
        assert "India Market & Economy News" in result
        assert "India GDP growth accelerates" in result

    @patch("tradingagents.dataflows.india_news.requests.get", side_effect=_mock_requests_get)
    def test_respects_limit(self, mock_get):
        result = get_global_news_india_rss("2026-05-09", look_back_days=14, limit=1)
        # Only 1 article should show (the most recent one)
        assert result.count("### ") == 1

    def test_invalid_date(self):
        result = get_global_news_india_rss("nope")
        assert "Invalid date format" in result
