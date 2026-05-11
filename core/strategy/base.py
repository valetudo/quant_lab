"""Strategy ABC — every strategy in quant_lab subclasses this."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from core.strategy.signals import Action, Position, Signal


class Strategy(ABC):
    """Base class for all quant_lab strategies.

    Lifecycle (called by the engine):
        on_init(history)                            — once before main loop
        on_retrain(date, history)                   — periodic (optional override)
        generate_signals(date, history, open_pos)   — every bar; returns list[Signal]
        manage_positions(date, history, open_pos)   — every bar; returns list[Action]
    """

    @property
    @abstractmethod
    def strategy_id(self) -> str: ...

    @property
    @abstractmethod
    def universe(self) -> list[str]: ...

    @abstractmethod
    def on_init(self, history: pd.DataFrame) -> None: ...

    def on_retrain(self, date: pd.Timestamp, history: pd.DataFrame) -> None:
        return None

    @abstractmethod
    def generate_signals(
        self,
        date: pd.Timestamp,
        history: pd.DataFrame,
        open_positions: list[Position],
    ) -> list[Signal]: ...

    @abstractmethod
    def manage_positions(
        self,
        date: pd.Timestamp,
        history: pd.DataFrame,
        open_positions: list[Position],
    ) -> list[Action]: ...
