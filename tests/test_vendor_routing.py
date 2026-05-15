"""Tests for vendor routing & empty-result detection in dataflows.interface.

These guard the fallback chain semantics that real pipeline runs depend on.
A regression here would silently feed the LLM empty news payloads and we'd
never notice in production logs (the original bug we're fixing).
"""

import logging
from unittest.mock import patch

import pytest

import tradingagents.dataflows.interface as itf
from tradingagents.dataflows.interface import (
    _is_empty_result,
    route_to_vendor,
)


# ---------------------------------------------------------------------------
# _is_empty_result
# ---------------------------------------------------------------------------


class TestIsEmptyResult:
    def test_none_is_empty(self):
        assert _is_empty_result(None) is True

    def test_empty_string_is_empty(self):
        assert _is_empty_result("") is True

    def test_marker_no_articles_found(self):
        assert _is_empty_result("No Indian news found for ONGC.NS") is True

    def test_marker_no_data(self):
        assert _is_empty_result("no data available") is True

    def test_alpha_vantage_zero_items_envelope(self):
        """The 145-char ``{"items":"0",...}`` JSON that AV returns for non-US tickers."""
        av_no_news = (
            '{"items": "0", "sentiment_score_definition": '
            '"x <= -0.35: Bearish; -0.15 < x <= 0.15: Neutral", '
            '"relevance_score_definition": "0 < x <= 1"}'
        )
        assert _is_empty_result(av_no_news) is True

    def test_alpha_vantage_zero_items_no_spaces(self):
        """Without whitespace between key and value (compact JSON)."""
        assert _is_empty_result('{"items":"0","feed":[]}') is True

    def test_real_news_payload_not_empty(self):
        real = (
            "## RELIANCE.NS News from Indian Sources, from 2026-05-08 to 2026-05-15:\n"
            "\n### Reliance posts record Q4 profit (source: Mint)\n"
            "Reliance Industries Limited reported a record net profit of..."
        )
        assert _is_empty_result(real) is False

    def test_long_string_not_flagged_by_marker(self):
        """A long valid response that happens to contain 'no' as a substring."""
        long_payload = "x" * 500 + " contains no anywhere"
        assert _is_empty_result(long_payload) is False

    def test_non_string_non_none_not_empty(self):
        assert _is_empty_result({"data": "yep"}) is False
        assert _is_empty_result(42) is False


# ---------------------------------------------------------------------------
# route_to_vendor — fallback chain
# ---------------------------------------------------------------------------


def _set_news_chain(chain: str):
    """Helper to force a specific news_data fallback chain."""
    from tradingagents.dataflows.config import set_config
    set_config({
        "data_vendors": {
            "core_stock_apis": "yfinance",
            "technical_indicators": "yfinance",
            "fundamental_data": "yfinance",
            "news_data": chain,
        },
        "tool_vendors": {},
    })


class TestRouteToVendor:
    def test_first_vendor_wins_when_non_empty(self, caplog):
        _set_news_chain("india_rss,google_rss")
        with patch.dict(itf.VENDOR_METHODS["get_news"], {
            "india_rss": lambda *a, **kw: "## TICKER.NS News from Indian Sources:\n\n### Real article (source: Mint)\nPlenty of body text here.",
            "google_rss": lambda *a, **kw: pytest.fail("should not have called google_rss"),
        }, clear=False):
            with caplog.at_level(logging.INFO):
                out = route_to_vendor("get_news", "TICKER.NS", "2026-05-08", "2026-05-15")

        assert "Real article" in out
        # Should NOT see an all-vendors-empty WARNING
        assert not any("ALL" in rec.message and "empty" in rec.message for rec in caplog.records)

    def test_falls_through_to_second_vendor_when_first_empty(self, caplog):
        _set_news_chain("india_rss,google_rss")
        with patch.dict(itf.VENDOR_METHODS["get_news"], {
            "india_rss": lambda *a, **kw: "No Indian news found for X",
            "google_rss": lambda *a, **kw: "## X News from Google News:\n\n### A real headline here\nWith real summary text padding it out beyond the empty threshold.",
        }, clear=False):
            with caplog.at_level(logging.INFO):
                out = route_to_vendor("get_news", "X", "2026-05-08", "2026-05-15")

        assert "real headline" in out
        # First vendor should have logged an "empty, trying next vendor" line
        assert any("india_rss returned empty" in rec.message for rec in caplog.records)

    def test_all_vendors_empty_emits_warning(self, caplog):
        """The original bug: when even the LAST vendor returned a tiny no-data envelope,
        we silently logged it as a successful 145-char return. Now it must WARN."""
        _set_news_chain("india_rss,google_rss")
        with patch.dict(itf.VENDOR_METHODS["get_news"], {
            "india_rss": lambda *a, **kw: "No Indian news found for X",
            "google_rss": lambda *a, **kw: '{"items": "0", "feed": []}',
        }, clear=False):
            with caplog.at_level(logging.WARNING):
                route_to_vendor("get_news", "GHOST.NS", "2026-05-08", "2026-05-15")

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "ALL" in r.message and "empty" in r.message and "GHOST.NS" in r.message
            for r in warnings
        ), f"expected all-vendors-empty WARNING, got: {[w.message for w in warnings]}"

    def test_av_zero_items_envelope_triggers_fallback(self, caplog):
        """Specifically guard against the ONGC/SUNPHARMA regression: AV's tiny
        ``{"items":"0"}`` payload must be treated as empty so the next vendor runs."""
        _set_news_chain("alpha_vantage,google_rss")
        with patch.dict(itf.VENDOR_METHODS["get_news"], {
            "alpha_vantage": lambda *a, **kw: '{"items": "0", "sentiment_score_definition": "..."}',
            "google_rss": lambda *a, **kw: "## ONGC.NS News from Google News:\n\n### ONGC wins pipeline contract\nReal coverage with body text.",
        }, clear=False):
            with caplog.at_level(logging.INFO):
                out = route_to_vendor("get_news", "ONGC.NS", "2026-05-08", "2026-05-15")

        assert "wins pipeline contract" in out
        assert any("alpha_vantage returned empty" in rec.message for rec in caplog.records)
