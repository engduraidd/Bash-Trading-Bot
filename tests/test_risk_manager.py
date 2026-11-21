import unittest
from decimal import Decimal

from risk_manager import calculate_trade


D = Decimal


class RiskManagerTests(unittest.TestCase):
    def test_long_and_short_without_costs(self):
        for direction, stop, target in (("LONG", "98.500", "104.500"),
                                        ("SHORT", "101.500", "95.500")):
            with self.subTest(direction=direction):
                trade = calculate_trade(direction, 100, 10, 100, fee_rate=0, slippage_rate=0)
                self.assertEqual(trade.stop_loss, D(stop))
                self.assertEqual(trade.take_profit, D(target))
                self.assertLessEqual(trade.max_loss, D("10"))
                self.assertAlmostEqual(trade.notional, D("666.6666666666"), places=8)
                self.assertEqual(trade.required_margin, trade.notional / 10)
                self.assertEqual(trade.actual_reward_ratio, 3)

    def test_costs_and_slippage_are_included_in_stop_risk(self):
        for direction in ("LONG", "SHORT"):
            with self.subTest(direction=direction):
                trade = calculate_trade(direction, 100, 10, 100, fee_rate="0.001", slippage_rate="0.0005")
                sign = D(1) if direction == "LONG" else D(-1)
                expected_loss = (sign * (trade.entry_price - trade.stop_exit_price) * trade.position_size
                                 + trade.estimated_stop_fees)
                self.assertAlmostEqual(trade.max_loss, expected_loss, places=24)
                self.assertLessEqual(trade.max_loss, D(10))
                self.assertLess(trade.actual_reward_ratio, D(3))
                self.assertEqual(trade.entry_price, D(100) * (1 + sign * D("0.0005")))
                self.assertLess(trade.notional, D("666.67"))

    def test_insufficient_margin_includes_opening_fee(self):
        trade = calculate_trade("LONG", 100, 10, 100, fee_rate="0.001", slippage_rate=0)
        with self.assertRaisesRegex(ValueError, "insufficient available margin"):
            calculate_trade("LONG", 100, 10, trade.required_margin, fee_rate="0.001", slippage_rate=0)
        calculate_trade("LONG", 100, 10, trade.required_margin + trade.entry_fee,
                        fee_rate="0.001", slippage_rate=0)

    def test_invalid_parameters(self):
        bad_cases = [dict(direction="BUY"), dict(entry_price=0), dict(entry_price="NaN"),
                     dict(leverage=0), dict(available_margin=-1), dict(risk_budget=11),
                     dict(risk_budget=0), dict(fee_rate=-1), dict(slippage_rate=1),
                     dict(stop_loss_pct=0), dict(reward_ratio=0), dict(fee_rate="0.1")]
        for case in bad_cases:
            args = dict(direction="LONG", entry_price=100, leverage=10, available_margin=100)
            args.update(case)
            with self.subTest(case=case), self.assertRaises(ValueError):
                calculate_trade(**args)


if __name__ == "__main__":
    unittest.main()
