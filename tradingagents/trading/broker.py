"""Abstract broker interface — paper and live share the same contract.

Design:
    BrokerInterface defines the contract.
    PaperBroker (paper_broker.py) — logs orders in SQLite, uses real prices.
    AngelOneBroker (angel_one.py) — real execution via SmartAPI.
    Factory: create_broker(config) returns the right implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Order:
    """Immutable record of a placed order."""

    order_id: str
    ticker: str
    side: str  # BUY or SELL
    quantity: int
    price: float
    total_value: float
    status: str  # FILLED, REJECTED
    rationale: Optional[str] = None
    pnl: Optional[float] = None  # Realized P&L (sells only)
    timestamp: Optional[str] = None


@dataclass(frozen=True)
class Holding:
    """Current position in a single ticker."""

    ticker: str
    quantity: int
    avg_price: float
    invested_value: float
    current_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Point-in-time portfolio summary."""

    cash: float
    holdings_value: float
    total_value: float
    daily_return_pct: Optional[float] = None
    holdings: Optional[list[Holding]] = None


class BrokerInterface(ABC):
    """Abstract broker — paper and live implementations share this contract."""

    @abstractmethod
    def get_ltp(self, ticker: str) -> float:
        """Get last traded price for a ticker.

        Args:
            ticker: NSE ticker with .NS suffix (e.g. ``RELIANCE.NS``).

        Returns:
            Last traded price in INR.
        """

    @abstractmethod
    def place_order(
        self,
        ticker: str,
        quantity: int,
        side: str,
        price: Optional[float] = None,
        rationale: Optional[str] = None,
    ) -> Order:
        """Place a buy/sell order.

        Args:
            ticker: NSE ticker (e.g. ``RELIANCE.NS``).
            quantity: Number of shares.
            side: ``BUY`` or ``SELL``.
            price: Limit price, or None for market order.
            rationale: Why this trade was made (from agent decision).

        Returns:
            Filled Order dataclass.
        """

    @abstractmethod
    def get_holdings(self) -> list[Holding]:
        """Get all current holdings with latest prices."""

    @abstractmethod
    def get_portfolio(self) -> PortfolioSnapshot:
        """Get full portfolio snapshot (cash + holdings)."""

    @abstractmethod
    def get_order_history(self, ticker: Optional[str] = None) -> list[Order]:
        """Get order history, optionally filtered by ticker."""

    @abstractmethod
    def get_cash(self) -> float:
        """Get available cash balance."""
