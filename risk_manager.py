"""Paper-trade sizing and estimated execution costs.

All prices passed to this module are quotes. Slippage is applied adversely to
both execution legs. Rates are fractions (0.001 means 0.1%), not percentages.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN


ZERO = Decimal("0")
ONE = Decimal("1")
MAX_RISK = Decimal("10")
SIZE_INCREMENT = Decimal("0.000000000001")


def _number(value, name):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{name} must be a finite number") from None
    if not number.is_finite():
        raise ValueError(f"{name} must be a finite number")
    return number


def _direction(value):
    if not isinstance(value, str) or value.upper() not in ("LONG", "SHORT"):
        raise ValueError("direction must be LONG or SHORT")
    return value.upper()


@dataclass(frozen=True)
class TradeCalculation:
    direction: str
    reference_entry_price: Decimal
    entry_price: Decimal
    position_size: Decimal
    leverage: Decimal
    notional: Decimal
    required_margin: Decimal
    entry_fee: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    stop_exit_price: Decimal
    take_profit_exit_price: Decimal
    max_loss: Decimal
    potential_reward: Decimal
    actual_reward_ratio: Decimal
    estimated_stop_fees: Decimal
    estimated_target_fees: Decimal
    fee_rate: Decimal
    slippage_rate: Decimal
    risk_budget: Decimal


def calculate_trade(direction, entry_price, leverage, available_margin,
                    risk_budget=10, stop_loss_pct="0.015", reward_ratio=3,
                    fee_rate="0.001", slippage_rate="0.0005"):
    """Size a trade at its risk budget, rejecting it if cash cannot fund it.

    The stop and target are trigger prices measured from the executed entry.
    The target is three times the stop distance by default; costs mean the
    estimated net reward/risk ratio will generally be less than three.
    """
    direction = _direction(direction)
    entry_quote = _number(entry_price, "entry price")
    leverage = _number(leverage, "leverage")
    available = _number(available_margin, "available margin")
    budget = _number(risk_budget, "risk budget")
    stop_pct = _number(stop_loss_pct, "stop loss percentage")
    reward_ratio = _number(reward_ratio, "reward ratio")
    fee = _number(fee_rate, "fee rate")
    slip = _number(slippage_rate, "slippage rate")
    if entry_quote <= ZERO:
        raise ValueError("entry price must be positive")
    if leverage < ONE:
        raise ValueError("leverage must be at least 1")
    if available < ZERO:
        raise ValueError("available margin cannot be negative")
    if budget <= ZERO or budget > MAX_RISK:
        raise ValueError("risk budget must be greater than zero and at most $10")
    if not ZERO < stop_pct < ONE:
        raise ValueError("stop loss percentage must be between 0 and 1")
    if reward_ratio <= ZERO:
        raise ValueError("reward ratio must be positive")
    if not ZERO <= fee < ONE or not ZERO <= slip < ONE:
        raise ValueError("fee and slippage rates must be at least 0 and less than 1")

    sign = ONE if direction == "LONG" else -ONE
    entry = entry_quote * (ONE + sign * slip)
    stop = entry * (ONE - sign * stop_pct)
    target = entry * (ONE + sign * stop_pct * reward_ratio)
    if stop <= ZERO or target <= ZERO:
        raise ValueError("stop loss and take profit prices must be positive")
    stop_exit = stop * (ONE - sign * slip)
    target_exit = target * (ONE - sign * slip)
    entry_fee_per_unit = entry * fee
    stop_fees_per_unit = entry_fee_per_unit + stop_exit * fee
    loss_per_unit = sign * (entry - stop_exit) + stop_fees_per_unit
    reward_per_unit = sign * (target_exit - entry) - entry_fee_per_unit - target_exit * fee
    if loss_per_unit <= ZERO or reward_per_unit <= ZERO:
        raise ValueError("estimated costs leave no positive target reward")
    try:
        size = (budget / loss_per_unit).quantize(SIZE_INCREMENT, rounding=ROUND_DOWN)
    except InvalidOperation:
        raise ValueError("position size is outside the supported range") from None
    if size <= ZERO:
        raise ValueError("position size is too small to calculate safely")
    notional = entry * size
    margin = notional / leverage
    opening_fee = entry_fee_per_unit * size
    if margin + opening_fee > available:
        raise ValueError(
            f"insufficient available margin: need ${margin + opening_fee:.4f} "
            f"including entry fee, but have ${available:.4f}"
        )
    loss = loss_per_unit * size
    reward = reward_per_unit * size
    return TradeCalculation(
        direction, entry_quote, entry, size, leverage, notional, margin,
        opening_fee, stop, target, stop_exit, target_exit, loss, reward,
        reward / loss, stop_fees_per_unit * size,
        (entry_fee_per_unit + target_exit * fee) * size, fee, slip, budget,
    )
