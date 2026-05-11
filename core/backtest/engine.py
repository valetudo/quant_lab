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

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from core.backtest.costs import leg_cost
from core.backtest.portfolio import Portfolio, Trade
from core.backtest.streaming import StreamWriter, update_every_for_span
from core.strategy.base import Strategy
from core.strategy.signals import Signal

log = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    equity: pd.DataFrame
    trades: list[Trade] = field(default_factory=list)
    open_count: pd.Series | None = None
    exposure: pd.Series | None = None
    early_stopped: bool = False
    stop_reason: str | None = None
    completion_pct: float = 1.0


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
        stream_writer: Optional[StreamWriter] = None,
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
        self.stream_writer = stream_writer

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
        entry_costs = sum(
            self._leg_cost(s, inst) for s, inst in zip(sig.target_sizes_eur, sig.instruments)
        )
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
            px = (
                self.panel[inst].loc[date]
                if (inst in self.panel.columns and date in self.panel.index)
                else float("nan")
            )
            prices.append(
                float(px) if pd.notna(px) else float(pos.entry_prices[pos.instruments.index(inst)])
            )
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
        n_bars = len(dates)
        sw = self.stream_writer
        update_every = update_every_for_span(int((dates[-1] - dates[0]).days)) if n_bars > 1 else 1

        # ---- benchmark series (SPY buy-and-hold) -------------------------
        # When the panel carries SPY, derive a per-date passive equity series
        # to emit alongside the strategy equity. Lets the UI overlay V5 vs SPY
        # in real time. If SPY is missing the bench dict stays empty and the
        # event payload just omits it (consumers handle absence).
        bench_symbol = "SPY"
        bench_at: dict = {}
        if bench_symbol in self.panel.columns:
            bs = self.panel[bench_symbol].astype(float).dropna()
            if not bs.empty and bs.iloc[0] > 0:
                bs_eq = self.portfolio.initial_capital * (bs / bs.iloc[0])
                bench_at = bs_eq.to_dict()

        history = self.panel.copy()  # full history; strategies receive a slice up to `date`
        self.strategy.on_init(history.iloc[:1])

        if sw is not None:
            sw.mark_started()
            sw.emit(
                dates[0],
                "started",
                {
                    "strategy_id": self.strategy.strategy_id,
                    "start": str(dates[0].date() if hasattr(dates[0], "date") else dates[0]),
                    "end": str(dates[-1].date() if hasattr(dates[-1], "date") else dates[-1]),
                    "initial_capital": float(self.portfolio.initial_capital),
                    "n_bars": int(n_bars),
                    "benchmark_symbol": bench_symbol if bench_at else None,
                },
            )

        early_stopped = False
        stop_reason: str | None = None
        last_processed_i = -1
        days_since_update = 0

        try:
            for i, date in enumerate(dates):
                # Cooperative cancellation: check at the top of every bar.
                if sw is not None and sw.is_cancel_requested():
                    early_stopped = True
                    stop_reason = "user_cancellation"
                    sw.emit(
                        date,
                        "stopped",
                        {"reason": stop_reason, "bars_processed": i, "bars_total": n_bars},
                    )
                    sw.mark_stopped()
                    break

                hist_slice = self.panel.iloc[: i + 1]

                if self.retrain_every_n_bars > 0 and i > 0 and i % self.retrain_every_n_bars == 0:
                    self.strategy.on_retrain(date, hist_slice)

                # 1. Manage open positions (close/reduce)
                prev_closed_n = len(self.portfolio.closed_trades)
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
                prev_open_ids = set(self.portfolio.open_positions.keys())
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

                # 4. Stream events (trade open/close always; equity throttled)
                if sw is not None:
                    newly_closed = self.portfolio.closed_trades[prev_closed_n:]
                    for t in newly_closed:
                        sw.emit(
                            date,
                            "trade_close",
                            {
                                "trade_id": t.trade_id,
                                "instruments": list(t.instruments),
                                "sides": list(t.sides),
                                "net_pnl_eur": float(t.net_pnl),
                                "duration_days": int(t.duration_days),
                                "exit_reason": str(t.exit_reason),
                            },
                        )
                    newly_opened_ids = set(self.portfolio.open_positions.keys()) - prev_open_ids
                    for pid in newly_opened_ids:
                        pos = self.portfolio.open_positions[pid]
                        sw.emit(
                            date,
                            "trade_open",
                            {
                                "trade_id": pos.position_id,
                                "instruments": list(pos.instruments),
                                "sides": list(pos.sides),
                                "sizes_eur": [float(s) for s in pos.sizes_eur],
                            },
                        )

                    days_since_update += 1
                    if days_since_update >= update_every or i == n_bars - 1:
                        eq_row = self.portfolio._equity_rows[-1]  # (date, cash, locked, equity)
                        exp = self.portfolio._exposure[-1] if self.portfolio._exposure else 0.0
                        bench_eq = bench_at.get(date)
                        payload = {
                            "equity_eur": float(eq_row[3]),
                            "cash_eur": float(eq_row[1]),
                            "locked_eur": float(eq_row[2]),
                            "n_open_positions": int(len(self.portfolio.open_positions)),
                            "gross_exposure_eur": float(exp),
                            "progress_pct": (i + 1) / n_bars,
                        }
                        if bench_eq is not None and pd.notna(bench_eq):
                            payload["benchmark_equity_eur"] = float(bench_eq)
                        sw.emit(date, "equity_update", payload)
                        days_since_update = 0

                last_processed_i = i

            # Close any leftover positions (on the final processed bar if we early-stopped,
            # or on the natural last bar otherwise — preserves the original behaviour).
            if last_processed_i >= 0:
                tail_date = dates[last_processed_i]
                prev_closed_n = len(self.portfolio.closed_trades)
                for pos in list(self.portfolio.open_positions.values()):
                    self._close_position(tail_date, pos, "eod")
                if sw is not None:
                    newly_closed = self.portfolio.closed_trades[prev_closed_n:]
                    for t in newly_closed:
                        sw.emit(
                            tail_date,
                            "trade_close",
                            {
                                "trade_id": t.trade_id,
                                "instruments": list(t.instruments),
                                "sides": list(t.sides),
                                "net_pnl_eur": float(t.net_pnl),
                                "duration_days": int(t.duration_days),
                                "exit_reason": str(t.exit_reason),
                            },
                        )

            if sw is not None and not early_stopped:
                final_eq = (
                    self.portfolio._equity_rows[-1][3] if self.portfolio._equity_rows else 0.0
                )
                sw.emit(
                    dates[-1],
                    "completed",
                    {
                        "final_equity_eur": float(final_eq),
                        "n_trades": int(len(self.portfolio.closed_trades)),
                    },
                )
                sw.mark_completed()

        except Exception as e:
            if sw is not None:
                err_date = dates[last_processed_i] if last_processed_i >= 0 else dates[0]
                sw.emit(err_date, "error", {"message": str(e)})
                sw.mark_error(str(e))
            raise

        completion_pct = ((last_processed_i + 1) / n_bars) if n_bars > 0 else 1.0
        return BacktestResult(
            equity=self.portfolio.equity_df(),
            trades=list(self.portfolio.closed_trades),
            open_count=self.portfolio.open_count_series(),
            exposure=self.portfolio.exposure_series(),
            early_stopped=early_stopped,
            stop_reason=stop_reason,
            completion_pct=float(completion_pct),
        )
