"""Walk-forward validation harness. Generalized from pair_trading_ITA.

Given a strategy factory and a wide price panel, split the timeline into
rolling (train, test) windows and run a backtest on each. Reports
per-fold OOS metrics so the caller can assess overfit / instability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from core.analytics.metrics import compute_metrics
from core.backtest.engine import PortfolioBacktester
from core.strategy.base import Strategy


@dataclass
class WalkForwardFold:
    fold_index: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    metrics: dict
    n_trades: int


@dataclass
class WalkForwardResult:
    folds: list[WalkForwardFold] = field(default_factory=list)

    def to_dataframe(self) -> pd.DataFrame:
        rows = [
            dict(
                fold=f.fold_index,
                train_start=f.train_start,
                train_end=f.train_end,
                test_start=f.test_start,
                test_end=f.test_end,
                **{
                    k: f.metrics.get(k)
                    for k in (
                        "sharpe",
                        "sortino",
                        "calmar",
                        "max_drawdown",
                        "total_return_pct",
                        "n_trades",
                    )
                },
            )
            for f in self.folds
        ]
        return pd.DataFrame(rows)


def rolling_windows(
    index: pd.DatetimeIndex,
    train_days: int,
    test_days: int,
    step_days: int | None = None,
) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """Return (train_start, train_end, test_start, test_end) tuples."""
    step = step_days or test_days
    out = []
    n = len(index)
    i = 0
    while i + train_days + test_days <= n:
        ts = index[i]
        te = index[i + train_days - 1]
        os = index[i + train_days]
        oe = index[min(i + train_days + test_days - 1, n - 1)]
        out.append((ts, te, os, oe))
        i += step
    return out


def walk_forward(
    panel: pd.DataFrame,
    strategy_factory: Callable[[], Strategy],
    *,
    train_days: int = 504,
    test_days: int = 252,
    step_days: int | None = None,
    initial_capital_eur: float = 50_000.0,
    commission_bps: float = 5.0,
    slippage_bps: float = 5.0,
) -> WalkForwardResult:
    """Run WF folds. `strategy_factory()` must return a fresh Strategy per fold."""
    out = WalkForwardResult()
    windows = rolling_windows(panel.index, train_days, test_days, step_days)
    for k, (_, te, os, oe) in enumerate(windows):
        test_panel = panel.loc[os:oe]
        if test_panel.empty:
            continue
        strat = strategy_factory()
        bt = PortfolioBacktester(
            strat,
            test_panel,
            initial_capital_eur=initial_capital_eur,
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
        )
        res = bt.run()
        eq = res.equity["equity"] if not res.equity.empty else pd.Series(dtype=float)
        metrics = compute_metrics(
            eq, res.trades, initial_capital_eur, open_count=res.open_count, exposure=res.exposure
        )
        out.folds.append(
            WalkForwardFold(
                fold_index=k,
                train_start=panel.index[max(0, panel.index.get_loc(te) - train_days + 1)],
                train_end=te,
                test_start=os,
                test_end=oe,
                metrics=metrics,
                n_trades=len(res.trades),
            )
        )
    return out
