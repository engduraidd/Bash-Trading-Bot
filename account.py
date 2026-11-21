"""Paper account accounting reconstructed entirely from the trade journal."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from journal import Journal, Trade


def _number(value, label: str, *, positive: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{label} must be a valid number") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError(f"{label} must be a finite positive number")
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _exit_value(trade: Trade, quote: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """Return estimated execution price, gross P&L and exit fee."""
    sign = Decimal(1) if trade.direction == "LONG" else Decimal(-1)
    exit_price = quote * (Decimal(1) - sign * trade.slippage_rate)
    gross = sign * (exit_price - trade.entry_price) * trade.position_size
    exit_fee = exit_price * trade.position_size * trade.fee_rate
    return exit_price, gross, exit_fee


@dataclass(frozen=True)
class AccountSnapshot:
    balance: Decimal
    equity: Decimal
    reserved_margin: Decimal
    available_margin: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal


class Account:
    def __init__(self, journal: Journal, initial_balance: Decimal = Decimal("100")) -> None:
        self.journal = journal
        self.initial_balance = _number(initial_balance, "Initial balance", positive=True)
        self.trades = journal.load()

    def snapshot(self, prices: dict[tuple[str, str], Decimal] | None = None) -> AccountSnapshot:
        prices = prices or {}
        realized = sum((trade.net_pnl for trade in self.trades if trade.status == "CLOSED"), Decimal(0))
        open_trades = [trade for trade in self.trades if trade.status == "OPEN"]
        entry_fees = sum((trade.entry_fee for trade in open_trades), Decimal(0))
        reserved = sum((trade.required_margin for trade in open_trades), Decimal(0))
        balance = self.initial_balance + realized - entry_fees
        unrealized = Decimal(0)
        for trade in open_trades:
            key = (trade.exchange, trade.symbol)
            if key not in prices:
                raise ValueError(f"Current price required for {trade.exchange} {trade.symbol}")
            quote = _number(prices[key], f"Price for {trade.symbol}", positive=True)
            _, gross, exit_fee = _exit_value(trade, quote)
            # Entry fees have already been deducted from balance.
            unrealized += gross - exit_fee
        equity = balance + unrealized
        available = max(Decimal(0), min(balance, equity) - reserved)
        return AccountSnapshot(balance, equity, reserved, available, realized, unrealized - entry_fees)

    def validate_open_trade(self, exchange: str, symbol: str, calculation, prices: dict[tuple[str, str], Decimal] | None = None) -> None:
        """Check margin using current prices without changing the account."""
        if not isinstance(exchange, str) or not exchange.strip() or not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("Exchange and symbol are required")
        available = self.snapshot(prices).available_margin
        key = (exchange.strip(), symbol.strip())
        reference_price = (prices or {}).get(key, calculation.reference_entry_price)
        quote = _number(reference_price, f"Price for {symbol}", positive=True)
        sign = Decimal(1) if calculation.direction == "LONG" else Decimal(-1)
        exit_price = quote * (Decimal(1) - sign * calculation.slippage_rate)
        gross = sign * (exit_price - calculation.entry_price) * calculation.position_size
        exit_fee = exit_price * calculation.position_size * calculation.fee_rate
        # Margin must still be covered after the new position is marked to market.
        immediate_loss = max(Decimal(0), exit_fee - gross)
        if calculation.required_margin + calculation.entry_fee + immediate_loss > available:
            raise ValueError("Insufficient available margin after entry and estimated closing costs")

    def open_trade(self, exchange: str, symbol: str, calculation, prices: dict[tuple[str, str], Decimal] | None = None) -> Trade:
        self.validate_open_trade(exchange, symbol, calculation, prices)
        trade_id = uuid4().hex
        while any(trade.trade_id == trade_id for trade in self.trades):
            trade_id = uuid4().hex
        trade = Trade(
            trade_id=trade_id, opened_at=_now(), exchange=exchange.strip(), symbol=symbol.strip(),
            direction=calculation.direction, entry_price=calculation.entry_price, exit_price=None,
            position_size=calculation.position_size, leverage=calculation.leverage,
            stop_loss=calculation.stop_loss, take_profit=calculation.take_profit,
            risk_amount=calculation.max_loss, gross_pnl=None, trading_fees=calculation.entry_fee,
            net_pnl=None, status="OPEN", closed_at="", required_margin=calculation.required_margin,
            entry_fee=calculation.entry_fee, exit_fee=None, fee_rate=calculation.fee_rate,
            slippage_rate=calculation.slippage_rate,
        )
        updated = [*self.trades, trade]
        self.journal.save(updated)
        self.trades = updated
        return trade

    def close_trade(self, trade_id: str, market_price: Decimal) -> Trade:
        quote = _number(market_price, "Market price", positive=True)
        trade = next((item for item in self.trades if item.trade_id == trade_id), None)
        if trade is None:
            raise ValueError(f"Trade not found: {trade_id}")
        if trade.status != "OPEN":
            raise ValueError(f"Trade is already closed: {trade_id}")
        exit_price, gross, exit_fee = _exit_value(trade, quote)
        total_fees = trade.entry_fee + exit_fee
        closed = replace(trade, exit_price=exit_price, gross_pnl=gross, exit_fee=exit_fee,
                         trading_fees=total_fees, net_pnl=gross - total_fees,
                         status="CLOSED", closed_at=_now())
        updated = [closed if item.trade_id == trade_id else item for item in self.trades]
        self.journal.save(updated)
        self.trades = updated
        return closed
