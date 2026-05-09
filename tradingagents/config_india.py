"""
Pre-built configuration for Indian stock markets (NSE/BSE).

Usage:
    from tradingagents.config_india import INDIA_CONFIG
    ta = TradingAgentsGraph(config={**DEFAULT_CONFIG, **INDIA_CONFIG})
"""

INDIA_CONFIG = {
    # Benchmark: NIFTY 50 index
    "benchmark_ticker": "^NSEI",
    "benchmark_name": "NIFTY 50",

    # Market context injected into every agent prompt
    "market_context": (
        "This is an Indian stock listed on NSE (National Stock Exchange) or BSE (Bombay Stock Exchange). "
        "Key India-specific factors to consider: "
        "RBI monetary policy and repo rate decisions; "
        "FII (Foreign Institutional Investor) and DII (Domestic Institutional Investor) flows; "
        "INR/USD exchange rate impact on export-oriented companies; "
        "SEBI regulatory changes; "
        "India VIX for volatility assessment; "
        "T+1 settlement cycle; "
        "Circuit limits (5%/10%/20% price bands) on individual stocks; "
        "Monsoon impact on agricultural and FMCG sectors; "
        "Union Budget and GST policy changes; "
        "Geopolitical factors (India-China, India-Pakistan tensions, BRICS dynamics). "
        "Currency is INR (Indian Rupee). Market hours: 9:15 AM - 3:30 PM IST."
    ),

    # India-centric global news search queries
    "global_news_queries": [
        "India stock market NSE BSE economy",
        "RBI monetary policy interest rate India",
        "FII DII investment flows India market",
        "India inflation GDP economic outlook",
        "India geopolitics trade policy",
    ],
}
