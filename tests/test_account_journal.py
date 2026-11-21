import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from account import Account
from journal import Journal, JournalError
from risk_manager import calculate_trade

D = Decimal


class AccountJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "trades.csv"
        self.account = Account(Journal(self.path))
        self.prices = {("binance", "BTC/USDT"): D("100")}

    def open(self, direction="LONG"):
        calculation = calculate_trade(direction, 100, 10, 100)
        return self.account.open_trade("binance", "BTC/USDT", calculation, self.prices)

    def test_open_and_restart_preserves_trade_and_account(self):
        trade = self.open()
        before = self.account.snapshot(self.prices)
        restored = Account(Journal(self.path))
        self.assertEqual(restored.trades, [trade])
        self.assertEqual(restored.snapshot(self.prices), before)
        self.assertEqual(before.balance, D(100) - trade.entry_fee)
        self.assertEqual(before.reserved_margin, trade.required_margin)
        self.assertGreaterEqual(before.available_margin, 0)
        self.assertEqual(before.equity, D(100) + before.unrealized_pnl)

    def test_long_close_fees_and_restart(self):
        trade = self.open()
        closed = self.account.close_trade(trade.trade_id, D("110"))
        expected_exit = D("110") * (1 - trade.slippage_rate)
        gross = (expected_exit - trade.entry_price) * trade.position_size
        fees = trade.entry_fee + expected_exit * trade.position_size * trade.fee_rate
        self.assertEqual(closed.exit_price, expected_exit)
        self.assertEqual(closed.gross_pnl, gross)
        self.assertEqual(closed.trading_fees, fees)
        self.assertEqual(closed.net_pnl, gross - fees)
        after = Account(Journal(self.path))
        snapshot = after.snapshot()
        self.assertEqual(snapshot.balance, D(100) + closed.net_pnl)
        self.assertEqual(snapshot.equity, snapshot.balance)
        self.assertEqual(snapshot.realized_pnl, closed.net_pnl)
        self.assertEqual(snapshot.reserved_margin, 0)
        self.assertEqual(after.trades, [closed])

    def test_short_close_profit_and_estimated_mark(self):
        trade = self.open("SHORT")
        quote = D("90")
        snapshot = self.account.snapshot({("binance", "BTC/USDT"): quote})
        closed = self.account.close_trade(trade.trade_id, quote)
        self.assertGreater(closed.net_pnl, 0)
        self.assertEqual(snapshot.equity, D(100) + closed.net_pnl)
        self.assertEqual(snapshot.unrealized_pnl, closed.net_pnl)

    def test_insufficient_margin_and_missing_quote_rejected_without_changes(self):
        self.open()
        before = self.path.read_bytes()
        calculation = calculate_trade("LONG", 100, 10, 100)
        with self.assertRaisesRegex(ValueError, "Current price required"):
            self.account.open_trade("binance", "ETH/USDT", calculation)
        with self.assertRaisesRegex(ValueError, "Insufficient"):
            self.account.open_trade("binance", "ETH/USDT", calculation, self.prices)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(len(self.account.trades), 1)

    def test_preview_checks_custom_entry_against_current_market_without_saving(self):
        calculation = calculate_trade("LONG", 100, 10, 100)
        with self.assertRaisesRegex(ValueError, "Insufficient"):
            self.account.validate_open_trade("binance", "BTC/USDT", calculation,
                                             {("binance", "BTC/USDT"): D("1")})
        self.assertFalse(self.path.exists())
        self.assertEqual(self.account.trades, [])

    def test_adverse_price_can_cause_negative_equity_but_not_negative_margin(self):
        self.open()
        snapshot = self.account.snapshot({("binance", "BTC/USDT"): D("0.01")})
        self.assertLess(snapshot.equity, 0)
        self.assertEqual(snapshot.available_margin, 0)

    def test_reject_invalid_prices_and_duplicate_closing(self):
        trade = self.open()
        for value in (0, -1, "NaN", "Infinity"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.account.close_trade(trade.trade_id, value)
        self.account.close_trade(trade.trade_id, 100)
        with self.assertRaisesRegex(ValueError, "already closed"):
            self.account.close_trade(trade.trade_id, 100)
        with self.assertRaisesRegex(ValueError, "not found"):
            self.account.close_trade("missing", 100)

    def test_malformed_or_external_edits_are_preserved(self):
        self.path.write_text("bad,columns\n1,2\n", encoding="utf-8")
        original = self.path.read_bytes()
        with self.assertRaises(JournalError):
            Account(Journal(self.path))
        self.assertEqual(original, self.path.read_bytes())
        calculation = calculate_trade("LONG", 100, 10, 100)
        with self.assertRaisesRegex(JournalError, "externally"):
            self.account.open_trade("binance", "BTC/USDT", calculation, self.prices)
        self.assertEqual(original, self.path.read_bytes())
        self.assertEqual(self.account.trades, [])

    def test_failed_write_does_not_modify_memory(self):
        calculation = calculate_trade("LONG", 100, 10, 100)
        with patch.object(self.account.journal, "save", side_effect=JournalError("failed")):
            with self.assertRaises(JournalError):
                self.account.open_trade("binance", "BTC/USDT", calculation, self.prices)
        self.assertEqual(self.account.trades, [])

    def test_duplicate_ids_rejected_on_load(self):
        self.open()
        content = self.path.read_text(encoding="utf-8")
        header, row = content.splitlines()
        self.path.write_text(header + "\n" + row + "\n" + row + "\n", encoding="utf-8")
        with self.assertRaisesRegex(JournalError, "Duplicate trade ID"):
            Account(Journal(self.path))


if __name__ == "__main__":
    unittest.main()
