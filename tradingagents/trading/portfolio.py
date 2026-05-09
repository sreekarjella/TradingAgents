"""Portfolio reporting — P&L, daily summaries, performance tracking.

Reads from the broker interface (paper or live) and generates
markdown reports consumed by agents and the CLI.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from .broker import BrokerInterface, PortfolioSnapshot

logger = logging.getLogger(__name__)


def portfolio_report(broker: BrokerInterface, benchmark_name: str = "NIFTY 50") -> str:
    """Generate a markdown portfolio report.

    Args:
        broker: Any BrokerInterface implementation.
        benchmark_name: Name of benchmark for display.

    Returns:
        Markdown-formatted portfolio report.
    """
    portfolio = broker.get_portfolio()
    orders = broker.get_order_history()

    # Header
    report = f"## 📊 Portfolio Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

    # Summary
    report += "### Summary\n"
    report += f"| Metric | Value |\n"
    report += f"|--------|-------|\n"
    report += f"| Cash | ₹{portfolio.cash:,.2f} |\n"
    report += f"| Holdings Value | ₹{portfolio.holdings_value:,.2f} |\n"
    report += f"| **Total Value** | **₹{portfolio.total_value:,.2f}** |\n"

    # Calculate total P&L if we have holdings
    if portfolio.holdings:
        total_unrealized = sum(h.unrealized_pnl or 0 for h in portfolio.holdings)
        total_invested = sum(h.invested_value for h in portfolio.holdings)
        pnl_pct = (total_unrealized / total_invested * 100) if total_invested > 0 else 0
        report += f"| Unrealized P&L | ₹{total_unrealized:,.2f} ({pnl_pct:+.1f}%) |\n"

    report += "\n"

    # Holdings table
    if portfolio.holdings:
        report += "### Current Holdings\n"
        report += "| Ticker | Qty | Avg Price | Current | P&L | P&L % |\n"
        report += "|--------|-----|-----------|---------|-----|-------|\n"
        for h in sorted(portfolio.holdings, key=lambda x: x.ticker):
            cur = h.current_price or h.avg_price
            pnl = h.unrealized_pnl or 0
            pnl_pct = (pnl / h.invested_value * 100) if h.invested_value > 0 else 0
            emoji = "🟢" if pnl >= 0 else "🔴"
            report += (
                f"| {h.ticker} | {h.quantity} | ₹{h.avg_price:,.2f} "
                f"| ₹{cur:,.2f} | {emoji} ₹{pnl:,.2f} | {pnl_pct:+.1f}% |\n"
            )
        report += "\n"
    else:
        report += "### Holdings\nNo positions currently held.\n\n"

    # Recent orders
    recent_orders = orders[:10]
    if recent_orders:
        report += "### Recent Orders (last 10)\n"
        report += "| Time | Ticker | Side | Qty | Price | Status |\n"
        report += "|------|--------|------|-----|-------|--------|\n"
        for o in recent_orders:
            ts = o.timestamp[:16] if o.timestamp else "—"
            report += (
                f"| {ts} | {o.ticker} | {o.side} "
                f"| {o.quantity} | ₹{o.price:,.2f} | {o.status} |\n"
            )
        report += "\n"

    return report


def daily_pnl_report(
    broker: BrokerInterface,
    benchmark_name: str = "NIFTY 50",
) -> str:
    """Generate a daily P&L summary for the trading log.

    Returns a compact 3-4 line summary suitable for agent context.
    """
    portfolio = broker.get_portfolio()
    today = datetime.now().strftime("%Y-%m-%d")

    total_unrealized = 0.0
    total_invested = 0.0
    if portfolio.holdings:
        total_unrealized = sum(h.unrealized_pnl or 0 for h in portfolio.holdings)
        total_invested = sum(h.invested_value for h in portfolio.holdings)

    pnl_pct = (total_unrealized / total_invested * 100) if total_invested > 0 else 0

    # Realized P&L from today's sells
    orders = broker.get_order_history()
    today_sells = [o for o in orders if o.side == "SELL" and o.timestamp and o.timestamp[:10] == today]
    realized = sum(o.pnl or 0 for o in today_sells)

    return (
        f"**{today}**: Portfolio ₹{portfolio.total_value:,.0f} "
        f"(Cash ₹{portfolio.cash:,.0f} + Holdings ₹{portfolio.holdings_value:,.0f}). "
        f"Unrealized P&L: ₹{total_unrealized:,.0f} ({pnl_pct:+.1f}%). "
        f"Today's realized: ₹{realized:,.0f}. "
        f"Positions: {len(portfolio.holdings or [])}."
    )
