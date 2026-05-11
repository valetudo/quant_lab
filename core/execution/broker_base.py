"""Broker ABC — scaffold for future live execution."""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.strategy.signals import Signal


class BrokerBase(ABC):
    @abstractmethod
    def submit(self, signal: Signal) -> str: ...

    @abstractmethod
    def cancel(self, order_id: str) -> bool: ...

    @abstractmethod
    def positions(self) -> list: ...

    @abstractmethod
    def balance(self) -> float: ...
