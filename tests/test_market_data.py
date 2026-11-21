import unittest
from decimal import Decimal
from unittest.mock import Mock

from market_data import MarketData, MarketDataError


class MarketDataTests(unittest.TestCase):
    def test_fetches_public_ticker_and_reuses_exchange(self):
        exchange = Mock()
        exchange.fetch_ticker.return_value = {"last": 123.45}
        factory = Mock(return_value=exchange)
        market = MarketData(factory)

        self.assertEqual(market.get_price("Binance", "btc/usdt"), Decimal("123.45"))
        self.assertEqual(market.get_price("binance", "ETH/USDT"), Decimal("123.45"))
        factory.assert_called_once_with("binance")
        self.assertEqual(exchange.fetch_ticker.call_args_list[0].args, ("BTC/USDT",))

    def test_network_failure_becomes_clear_market_error(self):
        exchange = Mock()
        exchange.fetch_ticker.side_effect = OSError("network unavailable")
        with self.assertRaisesRegex(MarketDataError, "Could not fetch BTC/USDT"):
            MarketData(lambda _: exchange).get_price("binance", "BTC/USDT")

    def test_bad_input_is_rejected_before_network_access(self):
        factory = Mock()
        market = MarketData(factory)
        for exchange, symbol in [("", "BTC/USDT"), ("bad-name", "BTC/USDT"),
                                 ("binance", ""), ("binance", "BTC / USDT")]:
            with self.subTest(exchange=exchange, symbol=symbol):
                with self.assertRaises(MarketDataError):
                    market.get_price(exchange, symbol)
        factory.assert_not_called()

    def test_missing_nonfinite_and_nonpositive_prices_are_rejected(self):
        exchange = Mock()
        market = MarketData(lambda _: exchange)
        for value in [None, 0, -1, "NaN", "Infinity", "not a price", True]:
            with self.subTest(value=value):
                exchange.fetch_ticker.return_value = {"last": value}
                with self.assertRaisesRegex(MarketDataError, "invalid last price"):
                    market.get_price("binance", "BTC/USDT")

    def test_unknown_exchange_error_is_preserved(self):
        def factory(_):
            raise MarketDataError("Unknown exchange: missing.")

        with self.assertRaisesRegex(MarketDataError, "Unknown exchange"):
            MarketData(factory).get_price("missing", "BTC/USDT")


if __name__ == "__main__":
    unittest.main()
