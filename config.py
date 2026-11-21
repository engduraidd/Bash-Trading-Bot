"""Configuration defaults for the local paper trading simulator."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os


def _number(name: str, default: str) -> Decimal:
    try:
        value = Decimal(os.environ.get(name, default))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not value.is_finite():
        raise ValueError(f"{name} must be a finite number")
    return value


@dataclass(frozen=True)
class Config:
    # Initial capital and maximum per-trade risk are fixed for this account.
    initial_balance: Decimal = Decimal("100")
    risk_budget: Decimal = Decimal("10")
    stop_loss_pct: Decimal = Decimal("0.015")
    reward_ratio: Decimal = Decimal("3")
    default_exchange: str = "binance"
    default_leverage: Decimal = Decimal("10")
    max_leverage: Decimal = Decimal("10")
    fee_rate: Decimal = Decimal("0.001")
    slippage_rate: Decimal = Decimal("0.0005")
    journal_path: str = "trades_journal.csv"

    @classmethod
    def from_environment(cls) -> "Config":
        config = cls(
            default_exchange=os.environ.get("PAPER_EXCHANGE", "binance").strip().lower(),
            default_leverage=_number("PAPER_LEVERAGE", "10"),
            max_leverage=_number("PAPER_MAX_LEVERAGE", "10"),
            fee_rate=_number("PAPER_FEE_RATE", "0.001"),
            slippage_rate=_number("PAPER_SLIPPAGE_RATE", "0.0005"),
            journal_path=os.environ.get("PAPER_JOURNAL", "trades_journal.csv"),
        )
        if not config.default_exchange or not config.journal_path:
            raise ValueError("Exchange and journal path must not be empty")
        if config.max_leverage < 1 or not 1 <= config.default_leverage <= config.max_leverage:
            raise ValueError("Leverage must be at least 1 and at most PAPER_MAX_LEVERAGE")
        if not 0 <= config.fee_rate < 1 or not 0 <= config.slippage_rate < 1:
            raise ValueError("Fee and slippage rates must be at least 0 and less than 1")
        return config
