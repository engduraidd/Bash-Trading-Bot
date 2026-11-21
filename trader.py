"""Interactive, local-only paper trading CLI. No exchange orders are sent."""

import cmd
from decimal import Decimal, InvalidOperation
import sys
import time

from account import Account
from config import Config
from journal import Journal, JournalError
from market_data import MarketData, MarketDataError
from risk_manager import calculate_trade


def money(value):
    return f"${value:,.2f}"


def ask(label, default=None):
    suffix = f" [{default}]" if default is not None else ""
    answer = input(f"{label}{suffix}: ").strip()
    return answer or (str(default) if default is not None else "")


def decimal_input(value, label):
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label} must be a number") from None
    if not result.is_finite():
        raise ValueError(f"{label} must be finite")
    return result


class TradingCLI(cmd.Cmd):
    intro = "Paper Trading CLI — simulated trades only. Type help for commands."
    prompt = "paper> "

    def __init__(self, config, account, market):
        super().__init__()
        self.config = config
        self.account = account
        self.market = market

    def _prices(self):
        return {(t.exchange, t.symbol): self.market.get_price(t.exchange, t.symbol)
                for t in self.account.trades if t.status == "OPEN"}

    def _run(self, action):
        try:
            action()
        except (ValueError, JournalError, MarketDataError, OSError) as exc:
            print(f"Error: {exc}")

    def do_dashboard(self, arg):
        """dashboard: Show cash balance, available margin, P&L and equity."""
        def action():
            s = self.account.snapshot(self._prices())
            print(f"Balance: {money(s.balance)} | Reserved margin: {money(s.reserved_margin)} | Available margin: {money(s.available_margin)}")
            print(f"Realized P&L: {money(s.realized_pnl)} | Unrealized P&L (after estimated costs): {money(s.unrealized_pnl)} | Equity: {money(s.equity)}")
            if s.equity < s.reserved_margin:
                print(f"Margin deficit: {money(s.reserved_margin - s.equity)}")
        self._run(action)

    def do_price(self, arg):
        """price [SYMBOL] [EXCHANGE]: Fetch a public market price."""
        def action():
            parts = arg.split()
            if len(parts) > 2:
                raise ValueError("Usage: price [SYMBOL] [EXCHANGE]")
            symbol = (parts[0] if parts else ask("Symbol", "BTC/USDT")).upper()
            exchange = (parts[1] if len(parts) > 1 else self.config.default_exchange).lower()
            print(f"{exchange} {symbol}: {self.market.get_price(exchange, symbol)}")
        self._run(action)

    def do_open(self, arg):
        """open: Preview and confirm a simulated LONG or SHORT trade."""
        def action():
            exchange = ask("Exchange", self.config.default_exchange).lower()
            symbol = ask("Symbol", "BTC/USDT").upper()
            if not symbol.endswith("/USDT") or symbol.count("/") != 1 or not symbol.split("/")[0]:
                raise ValueError("Paper trades require a BASE/USDT symbol so prices and risk are in USDT")
            direction = ask("Direction (LONG/SHORT)", "LONG").upper()
            leverage = decimal_input(ask("Leverage", self.config.default_leverage), "Leverage")
            if not 1 <= leverage <= self.config.max_leverage:
                raise ValueError(f"Leverage must be between 1 and {self.config.max_leverage}")
            market_price = self.market.get_price(exchange, symbol)
            quote = decimal_input(ask("Entry quote (current market price by default)", market_price), "Entry quote")
            prices = self._prices()
            prices[(exchange, symbol)] = market_price
            available = self.account.snapshot(prices).available_margin
            result = calculate_trade(direction, quote, leverage, available,
                                     risk_budget=self.config.risk_budget,
                                     stop_loss_pct=self.config.stop_loss_pct,
                                     reward_ratio=self.config.reward_ratio,
                                     fee_rate=self.config.fee_rate,
                                     slippage_rate=self.config.slippage_rate)
            self.account.validate_open_trade(exchange, symbol, result, prices)
            preview_time = time.monotonic()
            print(f"\nPreview: {direction} {symbol} on {exchange} (paper only)")
            print(f"Quote: {quote} | Estimated entry after slippage: {result.entry_price}")
            print(f"Size: {result.position_size} | Exposure: {money(result.notional)} | Margin: {money(result.required_margin)} | Leverage: {leverage}x")
            print(f"Stop: {result.stop_loss} | Target: {result.take_profit}")
            print(f"Estimated loss at stop including costs: {money(result.max_loss)} | Estimated net reward at target: {money(result.potential_reward)}")
            print(f"Estimated fees at stop: {money(result.estimated_stop_fees)} | Target: {money(result.estimated_target_fees)}")
            print(f"Price reward/risk: 3:1 | Estimated net reward/risk: {result.actual_reward_ratio:.2f}:1")
            print("Stop and target are reference levels; no automatic execution is performed.")
            if ask("Open this paper trade? (yes/no)", "no").lower() != "yes":
                print("Trade cancelled.")
                return
            if time.monotonic() - preview_time > 30:
                raise ValueError("Preview expired after 30 seconds; start open again for fresh prices")
            # Keep the confirmed simulated entry, but check all positions against
            # fresh quotes before saving, including any custom entry.
            prices = self._prices()
            prices[(exchange, symbol)] = self.market.get_price(exchange, symbol)
            if time.monotonic() - preview_time > 30:
                raise ValueError("Preview expired after 30 seconds; start open again for fresh prices")
            trade = self.account.open_trade(exchange, symbol, result, prices)
            print(f"Opened paper trade {trade.trade_id}.")
        self._run(action)

    def do_positions(self, arg):
        """positions: Show open paper positions and current quotes."""
        def action():
            trades = [t for t in self.account.trades if t.status == "OPEN"]
            if not trades:
                print("No open positions.")
                return
            prices = self._prices()
            for t in trades:
                print(f"{t.trade_id} | {t.exchange} {t.symbol} {t.direction} | entry {t.entry_price} | SL {t.stop_loss} | TP {t.take_profit} | current {prices[(t.exchange, t.symbol)]}")
            print("Stop and target levels do not close positions automatically.")
        self._run(action)

    def do_close(self, arg):
        """close [TRADE_ID]: Close an open paper position at the current quote."""
        def action():
            trade_id = arg.strip() or ask("Trade ID")
            trade = next((t for t in self.account.trades if t.trade_id == trade_id and t.status == "OPEN"), None)
            if trade is None:
                raise ValueError("Open trade not found; use positions to find its full ID")
            quote = self.market.get_price(trade.exchange, trade.symbol)
            closed = self.account.close_trade(trade_id, quote)
            print(f"Closed {trade_id}: quote {quote}, execution {closed.exit_price}, gross P&L {money(closed.gross_pnl)}, fees {money(closed.trading_fees)}, net P&L {money(closed.net_pnl)}")
        self._run(action)

    def do_history(self, arg):
        """history: Show completed paper trades."""
        trades = [t for t in self.account.trades if t.status == "CLOSED"]
        if not trades:
            print("No closed trades.")
        for t in trades:
            print(f"{t.trade_id} | {t.closed_at} | {t.exchange} {t.symbol} {t.direction} | entry {t.entry_price} | exit {t.exit_price} | net {money(t.net_pnl)}")

    def do_stats(self, arg):
        """stats: Show performance of closed paper trades."""
        trades = [t for t in self.account.trades if t.status == "CLOSED"]
        wins = sum(t.net_pnl > 0 for t in trades)
        total = sum((t.net_pnl for t in trades), Decimal(0))
        rate = Decimal(wins) / len(trades) * 100 if trades else Decimal(0)
        print(f"Closed trades: {len(trades)} | Wins: {wins} | Win rate: {rate:.1f}% | Net realized P&L: {money(total)}")

    def do_exit(self, arg):
        """exit: Leave the application."""
        return True

    do_quit = do_exit
    do_EOF = do_exit

    def emptyline(self):
        pass


def main():
    try:
        config = Config.from_environment()
        app = TradingCLI(config, Account(Journal(config.journal_path), config.initial_balance), MarketData())
        if len(sys.argv) > 1:
            app.onecmd(" ".join(sys.argv[1:]))
        else:
            app.cmdloop()
    except (ValueError, JournalError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nGoodbye.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
