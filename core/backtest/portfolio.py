"""Portfolio bookkeeping — cash, open positions, trades, equity curve.

Used by the generalized engine. Strategy-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

import pandas as pd

from quant_lab.core.strategy.signals import Position


@dataclass
class Trade:
    """Closed trade record — duck-typed for standard_schema and metrics."""
    trade_id: str
    strategy_id: str
    instruments: list[str]
    sides: list[str]
    sizes_eur: list[float]
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_prices: list[float]
    exit_prices: list[float]
    gross_pnl: float
    costs: float
    net_pnl: float
    duration_days: int
    exit_reason: str
    metadata: dict = field(default_factory=dict)


class Portfolio:
    """Tracks cash, locked margin, open positions, and the equity series."""

    def __init__(self, initial_capital_eur: float) -> None:
        self.initial_capital = float(initial_capital_eur)
        self.cash = float(initial_capital_eur)
        self.locked = 0.0
        self.open_positions: dict[str, Position] = {}
        self.closed_trades: list[Trade] = []
        self._equity_rows: list[tuple] = []  # (date, cash, locked, equity)
        self._open_count: list[int] = []
        self._exposure: list[float] = []

    def open_position(
        self,
        date: pd.Timestamp,
        strategy_id: str,
        instruments: list[str],
        sides: list[str],
        sizes_eur: list[float],
        prices: list[float],
        entry_costs: float,
        metadata: Optional[dict] = None,
    ) -> Position:
        position_id = uuid4().hex
        shares = [float(s) / float(p) for s, p in zip(sizes_eur, prices)]
        pos = Position(
            position_id=position_id,
            strategy_id=strategy_id,
            instruments=list(instruments),
            sides=list(sides),
            sizes_eur=list(sizes_eur),
            entry_date=date,
            entry_prices=list(prices),
            shares=shares,
            entry_costs_eur=float(entry_costs),
            metadata=dict(metadata or {}),
        )
        # Cash impact: for each leg, longs consume cash; shorts get collateral
        # set aside as "locked" (proceeds offset). Simple model: locked = Σ size.
        lock = sum(float(s) for s in sizes_eur)
        self.cash -= entry_costs
        self.locked += lock
        self.cash -= lock  # money set aside for the trade
        self.open_positions[position_id] = pos
        return pos

    def close_position(
        self,
        position_id: str,
        date: pd.Timestamp,
        prices: list[float],
        exit_costs: float,
        exit_reason: str,
    ) -> Trade:
        pos = self.open_positions.pop(position_id)
        gross = 0.0
        for inst, side, shares, p_entry, p_exit in zip(
            pos.instruments, pos.sides, pos.shares, pos.entry_prices, prices
        ):
            sign = 1.0 if side == "long" else -1.0
            gross += sign * (float(p_exit) - float(p_entry)) * float(shares)
        total_costs = float(pos.entry_costs_eur) + float(exit_costs)
        net = gross - total_costs
        # Release the locked notional and collect the gross P&L
        lock = sum(float(s) for s in pos.sizes_eur)
        self.cash += lock + gross - exit_costs
        self.locked -= lock
        duration = max(int((date - pos.entry_date).days), 0)
        trade = Trade(
            trade_id=pos.position_id,
            strategy_id=pos.strategy_id,
            instruments=list(pos.instruments),
            sides=list(pos.sides),
            sizes_eur=list(pos.sizes_eur),
            entry_date=pos.entry_date,
            exit_date=date,
            entry_prices=list(pos.entry_prices),
            exit_prices=list(prices),
            gross_pnl=gross,
            costs=total_costs,
            net_pnl=net,
            duration_days=duration,
            exit_reason=exit_reason,
            metadata=dict(pos.metadata),
        )
        self.closed_trades.append(trade)
        return trade

    def mark_to_market(self, date: pd.Timestamp, panel: pd.DataFrame) -> float:
        """Return the live unrealized P&L of all open positions on `date`."""
        live = 0.0
        exposure = 0.0
        for pos in self.open_positions.values():
            for inst, side, shares, p_entry in zip(
                pos.instruments, pos.sides, pos.shares, pos.entry_prices
            ):
                if inst not in panel.columns:
                    continue
                px = panel[inst].loc[date] if date in panel.index else float("nan")
                if not pd.notna(px):
                    continue
                sign = 1.0 if side == "long" else -1.0
                live += sign * (float(px) - float(p_entry)) * float(shares)
                exposure += abs(float(shares) * float(px))
        return live, exposure

    def record_equity(self, date: pd.Timestamp, panel: pd.DataFrame) -> None:
        live, exposure = self.mark_to_market(date, panel)
        equity = self.cash + self.locked + live
        self._equity_rows.append((date, self.cash, self.locked, equity))
        self._open_count.append(len(self.open_positions))
        self._exposure.append(exposure)

    def equity_df(self) -> pd.DataFrame:
        df = pd.DataFrame(self._equity_rows, columns=["date", "cash", "locked", "equity"])
        if not df.empty:
            df = df.set_index("date")
        return df

    def open_count_series(self) -> pd.Series:
        idx = [r[0] for r in self._equity_rows]
        return pd.Series(self._open_count, index=idx, name="n_open")

    def exposure_series(self) -> pd.Series:
        idx = [r[0] for r in self._equity_rows]
        return pd.Series(self._exposure, index=idx, name="gross_exposure")
