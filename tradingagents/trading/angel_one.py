"""Angel One SmartAPI broker — real market data and live order execution.

Requires these environment variables (or .env file):
    ANGEL_API_KEY       — SmartAPI API key
    ANGEL_CLIENT_ID     — Your Angel One client ID
    ANGEL_PASSWORD      — Your Angel One password
    ANGEL_TOTP_SECRET   — TOTP secret for 2FA (base32 encoded)

Docs: https://smartapi.angelone.in/docs
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

import pyotp
from SmartApi import SmartConnect

from .broker import BrokerInterface, Holding, Order, PortfolioSnapshot

logger = logging.getLogger(__name__)

# Angel One exchange codes
_EXCHANGE_NSE = "NSE"
_EXCHANGE_BSE = "BSE"
_PRODUCT_TYPE = "DELIVERY"  # CNC for delivery trades


def _strip_suffix(ticker: str) -> str:
    """Strip .NS/.BO suffix for Angel One API."""
    for suffix in (".NS", ".BO"):
        if ticker.upper().endswith(suffix):
            return ticker[: -len(suffix)]
    return ticker


class AngelOneBroker(BrokerInterface):
    """Live broker using Angel One SmartAPI.

    Args:
        api_key: SmartAPI API key (or env ANGEL_API_KEY).
        client_id: Angel One client ID (or env ANGEL_CLIENT_ID).
        password: Angel One password (or env ANGEL_PASSWORD).
        totp_secret: TOTP secret for 2FA (or env ANGEL_TOTP_SECRET).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        client_id: Optional[str] = None,
        password: Optional[str] = None,
        totp_secret: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("ANGEL_API_KEY", "")
        self.client_id = client_id or os.getenv("ANGEL_CLIENT_ID", "")
        self.password = password or os.getenv("ANGEL_PASSWORD", "")
        self.totp_secret = totp_secret or os.getenv("ANGEL_TOTP_SECRET", "")

        if not all([self.api_key, self.client_id, self.password, self.totp_secret]):
            raise ValueError(
                "Angel One credentials missing. Set ANGEL_API_KEY, ANGEL_CLIENT_ID, "
                "ANGEL_PASSWORD, and ANGEL_TOTP_SECRET in your .env file."
            )

        self._smart_api: Optional[SmartConnect] = None
        self._token_map: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _ensure_session(self) -> SmartConnect:
        """Authenticate and return a live SmartConnect session."""
        if self._smart_api is not None:
            return self._smart_api

        totp = pyotp.TOTP(self.totp_secret).now()

        self._smart_api = SmartConnect(api_key=self.api_key)
        session = self._smart_api.generateSession(
            self.client_id, self.password, totp
        )

        if session.get("status") is False:
            msg = session.get("message", "Unknown auth error")
            self._smart_api = None
            raise ConnectionError(f"Angel One auth failed: {msg}")

        logger.info("Angel One session established for %s", self.client_id)
        return self._smart_api

    def _get_token(self, ticker: str) -> dict:
        """Resolve ticker to Angel One symbol token.

        Returns dict with keys: symboltoken, tradingsymbol, exchange.
        """
        symbol = _strip_suffix(ticker)

        if symbol in self._token_map:
            return self._token_map[symbol]

        api = self._ensure_session()
        # Search for the symbol
        try:
            search_result = api.searchScrip(_EXCHANGE_NSE, symbol)
            if search_result and search_result.get("data"):
                token_info = search_result["data"][0]
                self._token_map[symbol] = {
                    "symboltoken": token_info["symboltoken"],
                    "tradingsymbol": token_info["tradingsymbol"],
                    "exchange": _EXCHANGE_NSE,
                }
                return self._token_map[symbol]
        except Exception as e:
            logger.warning("Symbol search failed for %s: %s", symbol, e)

        raise ValueError(f"Could not resolve Angel One token for {ticker}")

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def get_ltp(self, ticker: str) -> float:
        """Get last traded price from Angel One."""
        api = self._ensure_session()
        token = self._get_token(ticker)

        ltp_data = api.ltpData(
            token["exchange"],
            token["tradingsymbol"],
            token["symboltoken"],
        )

        if ltp_data and ltp_data.get("data"):
            return float(ltp_data["data"]["ltp"])

        raise ValueError(f"No LTP data for {ticker}")

    # ------------------------------------------------------------------
    # Order execution (REAL!)
    # ------------------------------------------------------------------

    def place_order(
        self,
        ticker: str,
        quantity: int,
        side: str,
        price: Optional[float] = None,
        rationale: Optional[str] = None,
    ) -> Order:
        """Place a REAL order on Angel One. Use with caution!"""
        side = side.upper()
        if side not in ("BUY", "SELL"):
            raise ValueError(f"Invalid side: {side}")
        if quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {quantity}")

        api = self._ensure_session()
        token = self._get_token(ticker)

        order_type = "LIMIT" if price else "MARKET"
        transaction_type = "BUY" if side == "BUY" else "SELL"

        order_params = {
            "variety": "NORMAL",
            "tradingsymbol": token["tradingsymbol"],
            "symboltoken": token["symboltoken"],
            "transactiontype": transaction_type,
            "exchange": token["exchange"],
            "ordertype": order_type,
            "producttype": _PRODUCT_TYPE,
            "duration": "DAY",
            "quantity": str(quantity),
        }

        if price:
            order_params["price"] = str(price)

        try:
            result = api.placeOrder(order_params)
            order_id = result if isinstance(result, str) else str(result)
            ltp = price or self.get_ltp(ticker)
            total_value = ltp * quantity

            logger.info(
                "LIVE %s: %s x%d @ ₹%.2f — order_id=%s",
                side, ticker, quantity, ltp, order_id,
            )

            return Order(
                order_id=order_id,
                ticker=ticker, side=side, quantity=quantity,
                price=ltp, total_value=total_value,
                status="FILLED", rationale=rationale,
                timestamp=datetime.now().isoformat(),
            )

        except Exception as e:
            logger.error("Order FAILED: %s %s x%d — %s", side, ticker, quantity, e)
            raise

    # ------------------------------------------------------------------
    # Portfolio queries
    # ------------------------------------------------------------------

    def get_holdings(self) -> list[Holding]:
        """Get real holdings from Angel One."""
        api = self._ensure_session()
        result = api.holding()

        if not result or not result.get("data"):
            return []

        return [
            Holding(
                ticker=h.get("tradingsymbol", "") + ".NS",
                quantity=int(h.get("quantity", 0)),
                avg_price=float(h.get("averageprice", 0)),
                invested_value=float(h.get("averageprice", 0)) * int(h.get("quantity", 0)),
                current_price=float(h.get("ltp", 0)),
                unrealized_pnl=float(h.get("profitandloss", 0)),
            )
            for h in result["data"]
            if int(h.get("quantity", 0)) > 0
        ]

    def get_portfolio(self) -> PortfolioSnapshot:
        """Get real portfolio from Angel One."""
        api = self._ensure_session()
        holdings = self.get_holdings()

        # Get funds
        funds = api.rmsLimit()
        cash = 0.0
        if funds and funds.get("data"):
            cash = float(funds["data"].get("availablecash", 0))

        holdings_value = sum(
            (h.current_price or h.avg_price) * h.quantity for h in holdings
        )

        return PortfolioSnapshot(
            cash=cash,
            holdings_value=holdings_value,
            total_value=cash + holdings_value,
            holdings=holdings,
        )

    def get_order_history(self, ticker: Optional[str] = None) -> list[Order]:
        """Get today's order book from Angel One."""
        api = self._ensure_session()
        result = api.orderBook()

        if not result or not result.get("data"):
            return []

        orders = []
        for o in result["data"]:
            t = o.get("tradingsymbol", "") + ".NS"
            if ticker and t != ticker:
                continue
            orders.append(Order(
                order_id=str(o.get("orderid", "")),
                ticker=t,
                side=o.get("transactiontype", ""),
                quantity=int(o.get("quantity", 0)),
                price=float(o.get("averageprice", 0)),
                total_value=float(o.get("averageprice", 0)) * int(o.get("quantity", 0)),
                status=o.get("orderstatus", ""),
                timestamp=o.get("updatetime", ""),
            ))
        return orders

    def get_cash(self) -> float:
        """Get available cash from Angel One."""
        api = self._ensure_session()
        funds = api.rmsLimit()
        if funds and funds.get("data"):
            return float(funds["data"].get("availablecash", 0))
        return 0.0
