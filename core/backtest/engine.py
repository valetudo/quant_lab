"""PortfolioBacktester — strategy-agnostic event-driven engine.

Generalized from pair_trading_ITA. The engine knows nothing about pairs,
cointegration, or any specific strategy. It drives any `Strategy`
subclass through generate_signals / manage_positions and tracks cash,
positions, costs, and the equity curve.

Execution model:
  - Daily close-of-day execution on each bar in `panel.index`.
  - Strategies emit Signals (open) and Actions (close/reduce) per bar.
  - Costs: linear-bps default; sqrt-volume optional with ADV map.
  - Sizing: strategies set target_sizes_eur per leg. Engine clips to
    available cash and skips if insufficient.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Optional

import numpy as np
import pandas as pd

from quant_lab.core.backtest.costs import leg_cost
from quant_lab.core.backtest.portfolio import Portfolio, Trade
from quant_lab.core.strategy.base import Strategy
from quant_lab.core.strategy.signals import Action, Signal

log = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    equity: pd.DataFrame
    trades: list[Trade] = field(default_factory=list)
    open_count: pd.Series | None = None
    exposure: pd.Series | None = None


class PortfolioBacktester:
    """Drive a single Strategy through `panel` and produce a BacktestResult."""

    def __init__(
        self,
        strategy: Strategy,
        panel: pd.DataFrame,
        *,
        initial_capital_eur: float = 50_000.0,
        commission_bps: float = 5.0,
        slippage_bps: float = 5.0,
        slippage_model: str = "linear_bps",
        avg_daily_turnover_eur: Optional[dict] = None,
        sqrt_impact_kappa: float = 0.10,
        retrain_every_n_bars: int = 0,
    ) -> None:
        if panel is None or panel.empty:
            raise ValueError("empty panel")
        self.strategy = strategy
        self.panel = panel
        self.portfolio = Portfolio(initial_capital_eur=initial_capital_eur)
        self.commission_bps = commission_bps
        self.slippage_bps = slippage_bps
        self.slippage_model = slippage_model
        self.adv = avg_daily_turnover_eur
        self.sqrt_kappa = sqrt_impact_kappa
        self.retrain_every_n_bars = int(retrain_every_n_bars)

    # ---- helpers ----------------------------------------------------------

    def _leg_cost(self, notional: float, ticker: str | None) -> float:
        return leg_cost(
            notional,
            commission_bps=self.commission_bps,
            slippage_bps=self.slippage_bps,
            ticker=ticker,
            slippage_model=self.slippage_model,
            avg_daily_turnover_eur=self.adv,
            sqrt_impact_kappa=self.sqrt_kappa,
        )

    def _open_from_signal(self, date: pd.Timestamp, sig: Signal) -> bool:
        """Validate prices, compute costs, sizes, and open the position. Returns True if opened."""
        prices: list[float] = []
        for inst in sig.instruments:
            if inst not in self.panel.columns:
                return False
            px = self.panel[inst].loc[date]
            if not pd.notna(px) or px <= 0:
                return False
            prices.append(float(px))
        entry_costs = sum(self._leg_cost(s, inst) for s, inst in zip(sig.target_sizes_eur, sig.instruments))
        lock_need = sum(float(s) for s in sig.target_sizes_eur)
        # Liquidity gate: clip sizes proportionally if insufficient cash.
        cash = self.portfolio.cash
        need = lock_need + entry_costs
        if cash < need:
            if cash <= 0:
                return False
            scale = max(0.0, cash / need * 0.999)
            if scale < 0.05:
                return False
            sizes = [float(s) * scale for s in sig.target_sizes_eur]
            entry_costs = sum(self._leg_cost(s, inst) for s, inst in zip(sizes, sig.instruments))
        else:
            sizes = list(sig.target_sizes_eur)
        self.portfolio.open_position(
            date=date,
            strategy_id=sig.strategy_id,
            instruments=list(sig.instruments),
            sides=list(sig.sides),
            sizes_eur=sizes,
            prices=prices,
            entry_costs=entry_costs,
            metadata=dict(sig.metadata),
        )
        return True

    def _close_position(self, date: pd.Timestamp, pos, reason: str) -> None:
        prices: list[float] = []
        for inst in pos.instruments:
            px = self.panel[inst].loc[date] if (inst in self.panel.columns and date in self.panel.index) else float("nan")
            prices.append(float(px) if pd.notna(px) else float(pos.entry_prices[pos.instruments.index(inst)]))
        exit_costs = sum(self._leg_cost(s, inst) for s, inst in zip(pos.sizes_eur, pos.instruments))
        self.portfolio.close_position(
            position_id=pos.position_id,
            date=date,
            prices=prices,
            exit_costs=exit_costs,
            exit_reason=reason,
        )

    # ---- main loop --------------------------------------------------------

    def run(self) -> BacktestResult:
        dates = self.panel.index
        history = self.panel.copy()  # full history; strategies receive a slice up to `date`
        self.strategy.on_init(history.iloc[:1])

        for i, date in enumerate(dates):
            hist_slice = self.panel.iloc[: i + 1]

            if self.retrain_every_n_bars > 0 and i > 0 and i % self.retrain_every_n_bars == 0:
                self.strategy.on_retrain(date, hist_slice)

            # 1. Manage open positions (close/reduce)
            open_list = list(self.portfolio.open_positions.values())
            try:
                actions = self.strategy.manage_positions(date, hist_slice, open_list) or []
            except Exception as e:
                log.warning("manage_positions error @ %s: %s", date, e)
                actions = []
            for act in actions:
                if act.action == "close":
                    pos = self.portfolio.open_positions.get(act.position_id)
                    if pos is not None:
                        self._close_position(date, pos, act.reason or "strategy_close")

            # 2. New signals
            open_list = list(self.portfolio.open_positions.values())
            try:
                signals = self.strategy.generate_signals(date, hist_slice, open_list) or []
            except Exception as e:
                log.warning("generate_signals error @ %s: %s", date, e)
                signals = []
            for sig in signals:
                if sig.action == "open":
                    self._open_from_signal(date, sig)
                elif sig.action == "close" and sig.position_id:
                    pos = self.portfolio.open_positions.get(sig.position_id)
                    if pos is not None:
                        self._close_position(date, pos, "strategy_close")

            # 3. Mark-to-market & record equity
            self.portfolio.record_equity(date, self.panel)

        # Close any leftover positions on the final bar
        last_day = dates[-1]
        for pos in list(self.portfolio.open_positions.values()):
            self._close_position(last_day, pos, "eod")

        return BacktestResult(
            equity=self.portfolio.equity_df(),
            trades=list(self.portfolio.closed_trades),
            open_count=self.portfolio.open_count_series(),
            exposure=self.portfolio.exposure_series(),
        )
