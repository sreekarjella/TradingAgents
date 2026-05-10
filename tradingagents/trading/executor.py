"""Trade executor — bridges agent decisions to broker orders.

Takes the pipeline's final decision (Buy/Overweight/Hold/Underweight/Sell)
and translates it into concrete trades with position sizing and guardrails.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from .broker import BrokerInterface, Order

logger = logging.getLogger(__name__)

# Default position sizing as % of total portfolio value.
# These are fallbacks — prefer loading from config.toml via TradingConfig.sizing.
_DEFAULT_SIZING = {
    "Buy": 0.05,         # 5% of portfolio per Buy
    "Overweight": 0.03,  # 3% — gradual increase
    "Underweight": 0.50, # Sell 50% of holding
    "Sell": 1.00,        # Sell 100% of holding
    "Hold": 0.00,        # No action
}

# Default guardrails — prefer loading from config.toml via TradingConfig.guardrails.
_DEFAULT_GUARDRAILS = {
    "max_position_pct": 0.10,       # Max 10% of portfolio in a single stock
    "min_trade_value": 500.0,       # Don't bother with trades under ₹500
    "max_trade_value": 100_000.0,   # Max ₹1L per single trade (safety cap)
}


@dataclass(frozen=True)
class TradeAction:
    """Resolved trade action from an agent decision."""

    ticker: str
    rating: str
    side: Optional[str]       # BUY, SELL, or None (Hold)
    quantity: int
    estimated_price: float
    estimated_value: float
    rationale: str
    skipped: bool = False
    skip_reason: Optional[str] = None


def parse_decision_details(decision_text: str) -> dict:
    """Extract structured details from the PM's markdown decision.

    Pulls out price_target, entry_price, stop_loss, position_sizing
    if they're present in the rendered markdown.
    """
    details: dict = {}

    patterns = {
        "price_target": r"\*\*Price Target\*\*:\s*([^\n]+)",
        "entry_price": r"\*\*Entry Price\*\*:\s*([^\n]+)",
        "stop_loss": r"\*\*Stop Loss\*\*:\s*([^\n]+)",
        "position_sizing": r"\*\*Position Sizing\*\*:\s*([^\n]+)",
        "time_horizon": r"\*\*Time Horizon\*\*:\s*([^\n]+)",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, decision_text, re.IGNORECASE)
        if match:
            val = match.group(1).strip()
            # Try to extract numeric value for price fields
            if key in ("price_target", "entry_price", "stop_loss"):
                num = re.search(r"[\d,]+\.?\d*", val.replace(",", ""))
                if num:
                    details[key] = float(num.group())
                else:
                    details[key] = val
            else:
                details[key] = val

    return details


def resolve_trade(
    ticker: str,
    rating: str,
    decision_text: str,
    broker: BrokerInterface,
    sizing_overrides: Optional[dict] = None,
    guardrails: Optional[dict] = None,
) -> TradeAction:
    """Resolve a pipeline decision into a concrete trade action.

    Args:
        ticker: Stock ticker (e.g. ``RELIANCE.NS``).
        rating: One of Buy/Overweight/Hold/Underweight/Sell.
        decision_text: Full PM decision markdown (for rationale + details).
        broker: Broker to query for portfolio state and prices.
        sizing_overrides: Optional dict overriding default sizing percentages.
            Keys: Buy, Overweight, Underweight, Sell (float values).
        guardrails: Optional dict with max_position_pct, min_trade_value,
            max_trade_value.  Loaded from config.toml when available.

    Returns:
        TradeAction with resolved quantity, price, and side.
    """
    sizing = {**_DEFAULT_SIZING, **(sizing_overrides or {})}
    guards = {**_DEFAULT_GUARDRAILS, **(guardrails or {})}

    # Hold = no action
    if rating == "Hold":
        return TradeAction(
            ticker=ticker, rating=rating, side=None, quantity=0,
            estimated_price=0, estimated_value=0,
            rationale="Hold — no action required.",
            skipped=True, skip_reason="Rating is Hold",
        )

    # Get current state
    try:
        ltp = broker.get_ltp(ticker)
    except Exception as e:
        return TradeAction(
            ticker=ticker, rating=rating, side=None, quantity=0,
            estimated_price=0, estimated_value=0,
            rationale=f"Could not fetch price: {e}",
            skipped=True, skip_reason=f"Price fetch failed: {e}",
        )

    portfolio = broker.get_portfolio()
    total_value = portfolio.total_value
    cash = portfolio.cash

    # Find current holding for this ticker
    current_holding = next(
        (h for h in (portfolio.holdings or []) if h.ticker == ticker), None
    )
    current_qty = current_holding.quantity if current_holding else 0
    current_value = current_qty * ltp

    details = parse_decision_details(decision_text)

    # Determine trade side and quantity
    if rating in ("Buy", "Overweight"):
        return _resolve_buy(
            ticker, rating, ltp, total_value, cash,
            current_value, sizing, guards, details, decision_text,
        )

    if rating in ("Sell", "Underweight"):
        return _resolve_sell(
            ticker, rating, ltp, current_qty,
            current_value, sizing, details, decision_text,
        )

    # Fallback (shouldn't happen with valid ratings)
    return TradeAction(
        ticker=ticker, rating=rating, side=None, quantity=0,
        estimated_price=ltp, estimated_value=0,
        rationale=f"Unknown rating: {rating}",
        skipped=True, skip_reason=f"Unrecognized rating: {rating}",
    )


def _resolve_buy(
    ticker: str, rating: str, ltp: float, total_value: float,
    cash: float, current_value: float, sizing: dict,
    guards: dict, details: dict, decision_text: str,
) -> TradeAction:
    """Resolve a Buy/Overweight into a concrete BUY order."""
    max_position_pct = guards["max_position_pct"]
    min_trade_value = guards["min_trade_value"]
    max_trade_value = guards["max_trade_value"]

    # Calculate allocation
    alloc_pct = sizing.get(rating, 0.05)
    target_value = total_value * alloc_pct

    # Guardrail: max position size
    max_allowed = total_value * max_position_pct
    remaining_room = max(0, max_allowed - current_value)

    if remaining_room <= min_trade_value:
        return TradeAction(
            ticker=ticker, rating=rating, side="BUY", quantity=0,
            estimated_price=ltp, estimated_value=0,
            rationale=f"Already at max position ({current_value / total_value:.0%} of portfolio)",
            skipped=True,
            skip_reason=f"Position already at {current_value / total_value:.0%} (max {max_position_pct:.0%})",
        )

    # Cap at remaining room, max trade value, and available cash
    trade_value = min(target_value, remaining_room, max_trade_value, cash)

    if trade_value < min_trade_value:
        reason = "Insufficient cash" if cash < min_trade_value else f"Trade too small (₹{trade_value:,.0f})"
        return TradeAction(
            ticker=ticker, rating=rating, side="BUY", quantity=0,
            estimated_price=ltp, estimated_value=0,
            rationale=reason, skipped=True, skip_reason=reason,
        )

    quantity = int(trade_value / ltp)
    if quantity <= 0:
        return TradeAction(
            ticker=ticker, rating=rating, side="BUY", quantity=0,
            estimated_price=ltp, estimated_value=0,
            rationale="Price too high for minimum allocation",
            skipped=True, skip_reason="Quantity would be zero",
        )

    actual_value = quantity * ltp
    rationale = (
        f"{rating} {ticker} — allocating {alloc_pct:.0%} of portfolio. "
        f"Buying {quantity} shares @ ₹{ltp:,.2f} = ₹{actual_value:,.0f}."
    )

    return TradeAction(
        ticker=ticker, rating=rating, side="BUY", quantity=quantity,
        estimated_price=ltp, estimated_value=actual_value,
        rationale=rationale,
    )


def _resolve_sell(
    ticker: str, rating: str, ltp: float, current_qty: int,
    current_value: float, sizing: dict, details: dict,
    decision_text: str,
) -> TradeAction:
    """Resolve a Sell/Underweight into a concrete SELL order."""
    if current_qty <= 0:
        return TradeAction(
            ticker=ticker, rating=rating, side="SELL", quantity=0,
            estimated_price=ltp, estimated_value=0,
            rationale=f"{rating} but no position held — nothing to sell.",
            skipped=True, skip_reason="No position held",
        )

    # Sell percentage of holding
    sell_pct = sizing.get(rating, 1.0)
    quantity = max(1, int(current_qty * sell_pct))

    # Sell can't exceed what we hold
    quantity = min(quantity, current_qty)
    actual_value = quantity * ltp

    rationale = (
        f"{rating} {ticker} — selling {sell_pct:.0%} of position. "
        f"Selling {quantity}/{current_qty} shares @ ₹{ltp:,.2f} = ₹{actual_value:,.0f}."
    )

    return TradeAction(
        ticker=ticker, rating=rating, side="SELL", quantity=quantity,
        estimated_price=ltp, estimated_value=actual_value,
        rationale=rationale,
    )


def execute_trade(
    trade: TradeAction,
    broker: BrokerInterface,
    dry_run: bool = False,
) -> Optional[Order]:
    """Execute a resolved trade action via the broker.

    Args:
        trade: Resolved TradeAction from ``resolve_trade``.
        broker: Broker implementation (paper or live).
        dry_run: If True, log but don't execute.

    Returns:
        Order if executed, None if skipped or dry run.
    """
    if trade.skipped:
        logger.info("SKIP %s %s: %s", trade.rating, trade.ticker, trade.skip_reason)
        return None

    if dry_run:
        logger.info(
            "DRY RUN: %s %s x%d @ ₹%.2f (₹%.0f)",
            trade.side, trade.ticker, trade.quantity,
            trade.estimated_price, trade.estimated_value,
        )
        return None

    logger.info(
        "EXECUTING: %s %s x%d @ ~₹%.2f",
        trade.side, trade.ticker, trade.quantity, trade.estimated_price,
    )

    return broker.place_order(
        ticker=trade.ticker,
        quantity=trade.quantity,
        side=trade.side,
        rationale=trade.rationale,
    )
