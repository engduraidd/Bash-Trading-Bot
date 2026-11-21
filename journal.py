"""Durable CSV storage for paper trades. No exchange credentials are stored."""
from __future__ import annotations

import csv
from dataclasses import dataclass, fields
from decimal import Decimal, InvalidOperation
import hashlib
import io
import os
from pathlib import Path
import tempfile


class JournalError(ValueError):
    """The journal is invalid, changed externally, or cannot be safely saved."""


@dataclass(frozen=True)
class Trade:
    trade_id: str
    opened_at: str
    exchange: str
    symbol: str
    direction: str
    entry_price: Decimal
    exit_price: Decimal | None
    position_size: Decimal
    leverage: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    risk_amount: Decimal
    gross_pnl: Decimal | None
    trading_fees: Decimal
    net_pnl: Decimal | None
    status: str
    closed_at: str
    required_margin: Decimal
    entry_fee: Decimal
    exit_fee: Decimal | None
    fee_rate: Decimal
    slippage_rate: Decimal


_COLUMNS = [field.name for field in fields(Trade)]
_DECIMALS = {"entry_price", "exit_price", "position_size", "leverage", "stop_loss", "take_profit", "risk_amount", "gross_pnl", "trading_fees", "net_pnl", "required_margin", "entry_fee", "exit_fee", "fee_rate", "slippage_rate"}
_OPTIONAL = {"exit_price", "gross_pnl", "net_pnl", "exit_fee"}


def _validate(trade: Trade) -> None:
    from datetime import datetime
    if not all(isinstance(getattr(trade, name), str) and getattr(trade, name).strip() for name in ("trade_id", "opened_at", "exchange", "symbol", "direction", "status")):
        raise JournalError("Journal contains a missing trade identifier or field")
    if trade.direction not in ("LONG", "SHORT") or trade.status not in ("OPEN", "CLOSED"):
        raise JournalError(f"Invalid direction or status for trade {trade.trade_id}")
    try:
        opened = datetime.fromisoformat(trade.opened_at)
        if opened.utcoffset() is None:
            raise ValueError("timezone required")
        if trade.closed_at:
            closed = datetime.fromisoformat(trade.closed_at)
            if closed.utcoffset() is None or closed < opened:
                raise ValueError("invalid closing time")
    except (ValueError, TypeError, OverflowError) as exc:
        raise JournalError(f"Invalid timestamp for trade {trade.trade_id}") from exc
    for name in _DECIMALS:
        value = getattr(trade, name)
        if value is None and name in _OPTIONAL:
            continue
        if not isinstance(value, Decimal) or not value.is_finite():
            raise JournalError(f"Invalid {name} for trade {trade.trade_id}")
    for name in ("entry_price", "position_size", "leverage", "stop_loss", "take_profit", "risk_amount", "required_margin"):
        if getattr(trade, name) <= 0:
            raise JournalError(f"{name} must be positive for trade {trade.trade_id}")
    if trade.exit_price is not None and trade.exit_price <= 0:
        raise JournalError(f"Exit price must be positive for trade {trade.trade_id}")
    if not (Decimal(0) <= trade.fee_rate < 1 and Decimal(0) <= trade.slippage_rate < 1):
        raise JournalError(f"Invalid fee or slippage rate for trade {trade.trade_id}")
    if trade.entry_fee < 0 or trade.trading_fees < 0 or (trade.exit_fee is not None and trade.exit_fee < 0):
        raise JournalError(f"Invalid fees for trade {trade.trade_id}")
    if trade.status == "OPEN":
        if trade.closed_at or any(getattr(trade, name) is not None for name in _OPTIONAL) or trade.trading_fees != trade.entry_fee:
            raise JournalError(f"Inconsistent open trade {trade.trade_id}")
    else:
        if not trade.closed_at or any(getattr(trade, name) is None for name in _OPTIONAL):
            raise JournalError(f"Incomplete closed trade {trade.trade_id}")
        if trade.trading_fees != trade.entry_fee + trade.exit_fee or trade.net_pnl != trade.gross_pnl - trade.trading_fees:
            raise JournalError(f"Inconsistent P&L or fees for trade {trade.trade_id}")


class Journal:
    """Read and atomically replace the complete trade history.

    A changed file is rejected rather than knowingly overwriting another writer's data.
    Only one running process should use a journal at a time.
    """
    def __init__(self, path: str | Path = "trades_journal.csv") -> None:
        self.path = Path(path)
        self._fingerprint: str | None = None
        self._loaded = False

    def _read(self) -> bytes | None:
        try:
            return self.path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise JournalError(f"Cannot read journal {self.path}: {exc}") from exc

    @staticmethod
    def _digest(data: bytes | None) -> str | None:
        return None if data is None else hashlib.sha256(data).hexdigest()

    def load(self) -> list[Trade]:
        data = self._read()
        if data is None:
            self._fingerprint, self._loaded = None, True
            return []
        try:
            reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""))
            if reader.fieldnames != _COLUMNS:
                raise JournalError("Journal columns do not match the expected format; the original file was preserved")
            trades = []
            seen = set()
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise JournalError("Journal contains a malformed row")
                values = dict(row)
                for name in _DECIMALS:
                    value = values[name]
                    values[name] = None if name in _OPTIONAL and value == "" else Decimal(value)
                trade = Trade(**values)
                _validate(trade)
                if trade.trade_id in seen:
                    raise JournalError(f"Duplicate trade ID: {trade.trade_id}")
                seen.add(trade.trade_id)
                trades.append(trade)
        except JournalError:
            raise
        except (UnicodeError, csv.Error, InvalidOperation, ValueError, TypeError) as exc:
            raise JournalError(f"Invalid journal; the original file was preserved: {exc}") from exc
        self._fingerprint, self._loaded = self._digest(data), True
        return trades

    def save(self, trades: list[Trade]) -> None:
        if not self._loaded:
            raise JournalError("Load the journal before saving it")
        seen = set()
        for trade in trades:
            _validate(trade)
            if trade.trade_id in seen:
                raise JournalError(f"Duplicate trade ID: {trade.trade_id}")
            seen.add(trade.trade_id)
        if self._digest(self._read()) != self._fingerprint:
            raise JournalError("Journal changed externally; restart before making changes")
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for trade in trades:
            writer.writerow({name: getattr(trade, name) if getattr(trade, name) is not None else "" for name in _COLUMNS})
        data = output.getvalue().encode("utf-8")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            temporary = None
        except OSError as exc:
            raise JournalError(f"Could not save journal: {exc}") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
        self._fingerprint = self._digest(data)
