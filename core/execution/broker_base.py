"""Broker ABC — scaffold for future live execution."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional

from quant_lab.core.strategy.signals import Signal


class BrokerBase(ABC):
    @abstractmethod
    def submit(self, signal: Signal) -> str: ...

    @abstractmethod
    def cancel(self, order_id: str) -> bool: ...

    @abstractmethod
    def positions(self) -> list: ...

    @abstractmethod
    def balance(self) -> float: ...
