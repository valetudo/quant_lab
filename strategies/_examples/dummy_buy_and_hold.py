"""DummyBuyAndHold — reference implementation of `Strategy`.

Buys a fixed list of tickers on the first bar with equal weight, holds to
the end, never sells. Used as the "Hello World" of the framework and as
fixture for engine smoke-tests.
"""
from __future__ import annotations

import pandas as pd

from quant_lab.core.strategy.base import Strategy
from quant_lab.core.strategy.signals import Action, Position, Signal


class DummyBuyAndHold(Strategy):
    def __init__(
        self,
        tickers: list[str],
        initial_capital_eur: float = 50_000.0,
        strategy_id: str = "dummy_buy_and_hold",
    ) -> None:
        self._strategy_id = strategy_id
        self._tickers = list(tickers)
        self._initial_capital_eur = float(initial_capital_eur)
        self._bought = False

    @property
    def strategy_id(self) -> str:
        return self._strategy_id

    @property
    def universe(self) -> list[str]:
        return list(self._tickers)

    def on_init(self, history: pd.DataFrame) -> None:
        self._bought = False

    def generate_signals(
        self,
        date: pd.Timestamp,
        history: pd.DataFrame,
        open_positions: list[Position],
    ) -> list[Signal]:
        if self._bought:
            return []
        avail = [t for t in self._tickers if t in history.columns
                 and pd.notna(history[t].loc[date])]
        if not avail:
            return []
        per_leg = self._initial_capital_eur / len(avail)
        self._bought = True
        return [
            Signal(
                strategy_id=self._strategy_id,
                instruments=[t],
                sides=["long"],
                target_sizes_eur=[per_leg],
                metadata={"reason": "buy_and_hold_init"},
            )
            for t in avail
        ]

    def manage_positions(
        self,
        date: pd.Timestamp,
        history: pd.DataFrame,
        open_positions: list[Position],
    ) -> list[Action]:
        return []
