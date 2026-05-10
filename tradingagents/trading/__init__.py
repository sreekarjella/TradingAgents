"""Trading package — broker interface, paper trading, and Angel One integration.

Usage:
    from tradingagents.trading import create_broker

    # Paper trading (default)
    broker = create_broker({"trading_mode": "paper"})

    # Live trading (Angel One)
    broker = create_broker({"trading_mode": "live"})
"""

from .broker import BrokerInterface, Holding, Order, PortfolioSnapshot
from .executor import TradeAction, execute_trade, resolve_trade
from .paper_broker import PaperBroker
from .portfolio import daily_pnl_report, portfolio_report
from .pre_screener import NIFTY_50, ScreenResult, pre_screen
from .run_tracker import RunTracker


def create_broker(config: dict) -> BrokerInterface:
    """Factory: create the right broker based on config.

    Args:
        config: Dict with at least ``trading_mode`` key.
            - ``"paper"`` (default): SQLite-backed paper trading.
            - ``"live"``: Angel One SmartAPI real execution.

    Returns:
        A BrokerInterface implementation.
    """
    mode = config.get("trading_mode", "paper")

    if mode == "paper":
        from pathlib import Path

        db_path = Path(config.get("paper_db_path", "data/paper_portfolio.db"))
        capital = config.get("initial_capital", 10_00_000.0)
        return PaperBroker(db_path=db_path, initial_capital=capital)

    if mode == "live":
        from .angel_one import AngelOneBroker

        return AngelOneBroker(
            api_key=config.get("angel_api_key"),
            client_id=config.get("angel_client_id"),
            password=config.get("angel_password"),
            totp_secret=config.get("angel_totp_secret"),
        )

    raise ValueError(f"Unknown trading_mode: {mode!r}. Use 'paper' or 'live'.")


__all__ = [
    "BrokerInterface",
    "Holding",
    "NIFTY_50",
    "Order",
    "PortfolioSnapshot",
    "PaperBroker",
    "RunTracker",
    "ScreenResult",
    "TradeAction",
    "create_broker",
    "daily_pnl_report",
    "execute_trade",
    "portfolio_report",
    "pre_screen",
    "resolve_trade",
]
