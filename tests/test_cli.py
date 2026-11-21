import contextlib
from decimal import Decimal
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from account import Account
from config import Config
from journal import Journal
from trader import TradingCLI


class FakeMarket:
    def get_price(self, exchange, symbol):
        return Decimal("100")


class CLITests(unittest.TestCase):
    def test_open_monitor_close_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.csv"
            account = Account(Journal(path))
            app = TradingCLI(Config(), account, FakeMarket())
            output = io.StringIO()
            with contextlib.redirect_stdout(output), patch("builtins.input", side_effect=["", "", "LONG", "", "", "yes"]):
                app.do_open("")
            self.assertEqual(len(account.trades), 1)
            self.assertIn("Estimated loss at stop", output.getvalue())
            trade_id = account.trades[0].trade_id
            restarted = TradingCLI(Config(), Account(Journal(path)), FakeMarket())
            with contextlib.redirect_stdout(output):
                restarted.do_positions("")
                restarted.do_dashboard("")
                restarted.do_close(trade_id)
            self.assertIn(trade_id, output.getvalue())
            self.assertEqual(Account(Journal(path)).trades[0].status, "CLOSED")
            self.assertLess(Account(Journal(path)).snapshot().balance, Decimal("100"))

    def test_declined_preview_does_not_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.csv"
            account = Account(Journal(path))
            app = TradingCLI(Config(), account, FakeMarket())
            with contextlib.redirect_stdout(io.StringIO()), patch("builtins.input", side_effect=["", "", "SHORT", "", "", "no"]):
                app.do_open("")
            self.assertEqual(account.trades, [])
            self.assertFalse(path.exists())

    def test_non_usdt_position_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            account = Account(Journal(Path(directory) / "journal.csv"))
            app = TradingCLI(Config(), account, FakeMarket())
            output = io.StringIO()
            with contextlib.redirect_stdout(output), patch("builtins.input", side_effect=["", "ETH/BTC"]):
                app.do_open("")
            self.assertIn("BASE/USDT", output.getvalue())
            self.assertEqual(account.trades, [])

    def test_expired_preview_does_not_open_trade(self):
        with tempfile.TemporaryDirectory() as directory:
            account = Account(Journal(Path(directory) / "journal.csv"))
            app = TradingCLI(Config(), account, FakeMarket())
            output = io.StringIO()
            with contextlib.redirect_stdout(output), patch("builtins.input", side_effect=["", "", "LONG", "", "", "yes"]), patch("trader.time.monotonic", side_effect=[0, 31]):
                app.do_open("")
            self.assertIn("expired", output.getvalue())
            self.assertEqual(account.trades, [])

    def test_margin_is_rechecked_after_confirmation(self):
        class FallingMarket:
            def __init__(self):
                self.prices = iter([Decimal("100"), Decimal("1")])

            def get_price(self, exchange, symbol):
                return next(self.prices)

        with tempfile.TemporaryDirectory() as directory:
            account = Account(Journal(Path(directory) / "journal.csv"))
            app = TradingCLI(Config(), account, FallingMarket())
            output = io.StringIO()
            with contextlib.redirect_stdout(output), patch("builtins.input", side_effect=["", "", "LONG", "", "", "yes"]):
                app.do_open("")
            self.assertIn("Insufficient available margin", output.getvalue())
            self.assertEqual(account.trades, [])


if __name__ == "__main__":
    unittest.main()
