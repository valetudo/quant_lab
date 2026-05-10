"""PaperBroker — in-memory order/position tracking. Scaffold only (no fills, no fees)."""
from __future__ import annotations
from uuid import uuid4

from quant_lab.core.execution.broker_base import BrokerBase
from quant_lab.core.strategy.signals import Signal


class PaperBroker(BrokerBase):
    def __init__(self, starting_cash_eur: float = 50_000.0) -> None:
        self._cash = float(starting_cash_eur)
        self._orders: dict[str, Signal] = {}
        self._positions: list = []

    def submit(self, signal: Signal) -> str:
        order_id = uuid4().hex
        self._orders[order_id] = signal
        return order_id

    def cancel(self, order_id: str) -> bool:
        return self._orders.pop(order_id, None) is not None

    def positions(self) -> list:
        return list(self._positions)

    def balance(self) -> float:
        return float(self._cash)
