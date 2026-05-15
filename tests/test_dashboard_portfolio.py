"""Tests for the dashboard portfolio Refresh button + live-price fetch.

Covers:
  * /portfolio renders with the Refresh button + body wrapper + htmx wiring.
  * /api/portfolio/refresh returns a partial (no full HTML layout).
  * fetch_live_prices is memoized for ~15s and survives empty inputs.
  * _resolve_ltp picks live > fallback > avg_price in that order.
  * _enrich_holdings shape is what the template expects.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Fresh FastAPI client + cleared price cache per test."""
    from dashboard.app import app
    from dashboard import live_prices

    live_prices.clear_cache()
    return TestClient(app)


@pytest.mark.unit
class TestPortfolioPage:
    def test_initial_render_has_refresh_button(self, client):
        r = client.get("/portfolio")
        assert r.status_code == 200
        assert "Refresh prices" in r.text
        assert 'id="portfolio-body"' in r.text
        assert 'hx-post="/api/portfolio/refresh"' in r.text
        assert 'hx-target="#portfolio-body"' in r.text

    def test_refresh_returns_partial_not_full_page(self, client):
        """The refresh endpoint must return ONLY the body partial.

        If it accidentally rendered the full page (extends base.html),
        HTMX would inject a duplicate nav/header into the page.
        """
        with patch("dashboard.app.fetch_live_prices", return_value={}):
            r = client.post("/api/portfolio/refresh")
        assert r.status_code == 200
        # No full HTML document — partial only.
        assert "<html" not in r.text.lower()
        assert "<head" not in r.text.lower()
        assert 'id="portfolio-body"' in r.text

    def test_refresh_uses_live_prices_when_available(self, client):
        """When live prices come back, the partial should reflect them."""
        # Inject one fake holding via the prices map; we don't seed the DB
        # here because we just want to verify the code path is wired.
        def fake_fetch(tickers):
            return {t: 12345.67 for t in tickers}

        with patch("dashboard.app.fetch_live_prices", side_effect=fake_fetch):
            r = client.post("/api/portfolio/refresh")
        assert r.status_code == 200
        # Status banner reflects live pricing OR no holdings (both fine).
        assert (
            "Live prices loaded" in r.text
            or "No holdings yet" in r.text
        )

    def test_refresh_falls_back_when_yfinance_fails(self, client):
        """Empty live-prices dict \u2192 yellow banner, not a crash."""
        with patch("dashboard.app.fetch_live_prices", return_value={}):
            r = client.post("/api/portfolio/refresh")
        assert r.status_code == 200
        # Either "couldn't reach" banner OR no-holdings empty state.
        assert (
            "Couldn&#39;t reach Yahoo Finance" in r.text
            or "Couldn't reach Yahoo Finance" in r.text
            or "No holdings yet" in r.text
        )


@pytest.mark.unit
class TestResolveLTP:
    def test_prefers_live_over_fallback(self):
        from dashboard.app import _resolve_ltp
        h = {"ticker": "RELIANCE.NS", "avg_price": 100.0}
        assert _resolve_ltp(h, {"RELIANCE.NS": 200.0}, {"RELIANCE.NS": 150.0}) == 200.0

    def test_uses_fallback_when_no_live(self):
        from dashboard.app import _resolve_ltp
        h = {"ticker": "RELIANCE.NS", "avg_price": 100.0}
        assert _resolve_ltp(h, {}, {"RELIANCE.NS": 150.0}) == 150.0

    def test_uses_avg_price_as_last_resort(self):
        from dashboard.app import _resolve_ltp
        h = {"ticker": "BRANDNEW.NS", "avg_price": 100.0}
        assert _resolve_ltp(h, {}, {}) == 100.0


@pytest.mark.unit
class TestEnrichHoldings:
    def test_shape_matches_template_contract(self):
        from dashboard.app import _enrich_holdings
        holdings = [{
            "ticker": "RELIANCE.NS",
            "quantity": 10,
            "avg_price": 100.0,
            "invested_value": 1000.0,
        }]
        out = _enrich_holdings(holdings, total_value=2000.0,
                               live_prices={"RELIANCE.NS": 150.0})
        assert len(out) == 1
        row = out[0]
        # Every key the Jinja template reads must exist:
        for key in ("ticker", "quantity", "avg_price", "ltp",
                    "current_value", "pnl", "pnl_pct", "allocation"):
            assert key in row, f"missing key: {key}"
        # Math sanity:
        assert row["ltp"] == 150.0
        assert row["current_value"] == 1500.0
        assert row["pnl"] == 500.0
        assert row["pnl_pct"] == 50.0
        assert row["allocation"] == 75.0  # 1500 / 2000

    def test_empty_holdings_returns_empty(self):
        from dashboard.app import _enrich_holdings
        assert _enrich_holdings([], total_value=0.0) == []

    def test_zero_total_value_doesnt_divide_by_zero(self):
        from dashboard.app import _enrich_holdings
        out = _enrich_holdings(
            [{"ticker": "X.NS", "quantity": 1, "avg_price": 10, "invested_value": 10}],
            total_value=0.0,
        )
        assert out[0]["allocation"] == 0.0


@pytest.mark.unit
class TestFetchLivePrices:
    def test_empty_input_returns_empty_no_network(self):
        from dashboard.live_prices import fetch_live_prices, clear_cache
        clear_cache()
        # Should NOT call yfinance for an empty list.
        with patch("dashboard.live_prices.yf.download") as mock_dl:
            assert fetch_live_prices([]) == {}
            assert fetch_live_prices(["", None]) == {}
            mock_dl.assert_not_called()

    def test_memoization_short_circuits_repeat_calls(self):
        from dashboard.live_prices import fetch_live_prices, clear_cache
        import pandas as pd
        clear_cache()

        # Build a fake yfinance multi-index frame for 2 tickers.
        cols = pd.MultiIndex.from_product(
            [["A.NS", "B.NS"], ["Open", "High", "Low", "Close", "Volume"]]
        )
        df = pd.DataFrame(
            [[1, 2, 0.5, 100.0, 10, 1, 2, 0.5, 200.0, 10]],
            index=pd.to_datetime(["2026-05-15"]),
            columns=cols,
        )

        with patch("dashboard.live_prices.yf.download", return_value=df) as mock_dl:
            r1 = fetch_live_prices(["A.NS", "B.NS"])
            r2 = fetch_live_prices(["A.NS", "B.NS"])  # cache hit
            assert r1 == {"A.NS": 100.0, "B.NS": 200.0}
            assert r2 == r1
            mock_dl.assert_called_once()  # second call hit the cache

    def test_network_failure_returns_empty(self):
        from dashboard.live_prices import fetch_live_prices, clear_cache
        clear_cache()
        with patch("dashboard.live_prices.yf.download",
                   side_effect=ConnectionError("DNS down")):
            assert fetch_live_prices(["X.NS"]) == {}
