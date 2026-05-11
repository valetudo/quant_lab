"""Signal, Action and Position dataclasses — strategy ↔ engine contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Signal:
    """A trade intent emitted by a strategy.

    The engine treats each Signal as a *group* of legs that must execute
    together (single-instrument signals are just a 1-leg group).

    `target_sizes_eur` is the EUR notional per leg. `sides` is per-leg
    ('long' or 'short'). `metadata` is free-form context (z-score,
    rank, yield, etc.) preserved into the trade log.
    """

    strategy_id: str
    instruments: list[str]
    sides: list[str]
    target_sizes_eur: list[float]
    metadata: dict = field(default_factory=dict)
    action: str = "open"  # 'open' | 'close' | 'rebalance'
    position_id: Optional[str] = None  # for 'close' / 'rebalance'


@dataclass
class Action:
    """A directive emitted by manage_positions() to close or adjust an existing position."""

    position_id: str
    action: str  # 'close' | 'reduce'
    reason: str = ""
    fraction: float = 1.0  # for 'reduce'


@dataclass
class Position:
    """Live state of an open position, tracked by the engine and read by strategies."""

    position_id: str
    strategy_id: str
    instruments: list[str]
    sides: list[str]
    sizes_eur: list[float]
    entry_date: object  # pd.Timestamp
    entry_prices: list[float]
    shares: list[float]
    entry_costs_eur: float = 0.0
    metadata: dict = field(default_factory=dict)
