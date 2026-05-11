"""Master Allocator — strategy-of-strategies capital allocation.

Phase 2: scaffold only. EqualWeightAllocator is the default. The
regime-aware variant lands in Phase 3 once we have >= 2 working
strategies whose correlation profile is measured.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Optional

import pandas as pd


class MasterAllocator(ABC):
    """Decides per-strategy capital fractions on each rebalance date.

    Returns a dict {strategy_id: weight}. Sum may be < 1.0 (residual = cash).
    """

    @abstractmethod
    def compute_weights(
        self,
        date: pd.Timestamp,
        strategy_states: dict,
        market_data: Optional[pd.DataFrame] = None,
    ) -> dict[str, float]: ...


class EqualWeightAllocator(MasterAllocator):
    """Equal allocation across all registered strategies.

    `cash_reserve` is a fraction of capital reserved as cash (e.g. 0.05 = 5%).
    """

    def __init__(self, strategy_ids: Iterable[str], cash_reserve: float = 0.0) -> None:
        self.strategy_ids = list(strategy_ids)
        self.cash_reserve = float(cash_reserve)
        if not (0.0 <= self.cash_reserve < 1.0):
            raise ValueError(f"cash_reserve must be in [0,1): {cash_reserve}")

    def compute_weights(self, date, strategy_states=None, market_data=None) -> dict[str, float]:
        n = len(self.strategy_ids)
        if n == 0:
            return {}
        w = (1.0 - self.cash_reserve) / n
        return {sid: w for sid in self.strategy_ids}


class FixedWeightAllocator(MasterAllocator):
    """Allocator with pre-set static weights (loaded from configs/allocation.yaml)."""

    def __init__(self, weights: dict[str, float]) -> None:
        s = sum(weights.values())
        if s <= 0 or s > 1.0 + 1e-6:
            raise ValueError(f"weights must sum to (0, 1]; got {s}")
        self.weights = dict(weights)

    def compute_weights(self, date, strategy_states=None, market_data=None) -> dict[str, float]:
        return dict(self.weights)


class RegimeAwareAllocator(MasterAllocator):
    """Placeholder for Phase 3 — regime-driven dynamic allocation.

    Sketch:
      - Bull regime  : 70% quality_stocks, 20% bonds_income, 10% reserve
      - Neutral     : 50% / 30% / 20%
      - Bear        : 20% / 60% / 20%

    Regime detection via VIX percentile + term spread + market breadth.
    """

    def compute_weights(self, date, strategy_states=None, market_data=None) -> dict[str, float]:
        raise NotImplementedError("RegimeAwareAllocator lands in Phase 3")
