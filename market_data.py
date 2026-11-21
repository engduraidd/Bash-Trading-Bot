"""Public cryptocurrency prices. This module never submits exchange orders."""

from decimal import Decimal, InvalidOperation
import re
from typing import Callable


class MarketDataError(Exception):
    """A public market price could not be obtained or was invalid."""


class MarketData:
    """Fetch last-traded prices using CCXT's public ticker endpoint.

    An optional factory makes it possible to test without an exchange or network.
    """

    def __init__(self, exchange_factory: Callable | None = None):
        self._exchange_factory = exchange_factory or self._create_exchange
        self._exchanges = {}

    @staticmethod
    def _create_exchange(exchange_id: str):
        try:
            import ccxt
        except ImportError as exc:
            raise MarketDataError(
                "CCXT is not installed. Install the dependencies in requirements.txt."
            ) from exc

        if exchange_id not in ccxt.exchanges:
            raise MarketDataError(f"Unknown exchange: {exchange_id}.")
        exchange_class = getattr(ccxt, exchange_id)
        # No API keys are supplied: only public market-data endpoints are used.
        return exchange_class({"enableRateLimit": True, "timeout": 10000})

    def get_price(self, exchange: str, symbol: str) -> Decimal:
        """Return a positive last-traded price or raise MarketDataError."""
        if not isinstance(exchange, str) or not re.fullmatch(
            r"[a-z0-9_]+", exchange.strip().lower()
        ):
            raise MarketDataError("Enter a valid exchange name, such as binance.")
        if not isinstance(symbol, str) or not symbol.strip() or any(
            char.isspace() for char in symbol.strip()
        ):
            raise MarketDataError("Enter a valid symbol, such as BTC/USDT.")
        exchange_id = exchange.strip().lower()
        normalized_symbol = symbol.strip().upper()

        try:
            if exchange_id not in self._exchanges:
                self._exchanges[exchange_id] = self._exchange_factory(exchange_id)
            ticker = self._exchanges[exchange_id].fetch_ticker(normalized_symbol)
        except MarketDataError:
            raise
        except Exception as exc:
            raise MarketDataError(
                f"Could not fetch {normalized_symbol} from {exchange_id}: {exc}"
            ) from exc

        try:
            value = ticker.get("last")
            if value is None or isinstance(value, bool):
                raise ValueError("missing last price")
            price = Decimal(str(value))
            if not price.is_finite() or price <= 0:
                raise ValueError("last price must be positive and finite")
        except (AttributeError, InvalidOperation, TypeError, ValueError) as exc:
            raise MarketDataError(
                f"{exchange_id} returned an invalid last price for {normalized_symbol}."
            ) from exc
        return price
