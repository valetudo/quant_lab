"""Performance metrics — robust to short series and zero variance.

Migrated and generalized from pair_trading_ITA. The trade-stats branch
reads from generic Trade objects (any object with `.net_pnl` and
`.duration_days`), not pair-specific TradeRecord.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd


def _safe_div(a: float, b: float) -> float:
    return float(a / b) if b not in (0, 0.0) and np.isfinite(b) else float("nan")


def cagr(equity: pd.Series, trading_days: int = 252) -> float:
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return float("nan")
    years = len(equity) / trading_days
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1) if years > 0 else float("nan")


def annualised_vol(returns: pd.Series, trading_days: int = 252) -> float:
    if returns.empty or returns.std(ddof=1) == 0:
        return 0.0
    return float(returns.std(ddof=1) * np.sqrt(trading_days))


def sharpe(returns: pd.Series, rf: float = 0.0, trading_days: int = 252) -> float:
    if returns.empty:
        return float("nan")
    excess = returns - rf / trading_days
    s = excess.std(ddof=1)
    if s == 0 or not np.isfinite(s):
        return float("nan")
    return float(excess.mean() / s * np.sqrt(trading_days))


def sortino(returns: pd.Series, rf: float = 0.0, trading_days: int = 252) -> float:
    if returns.empty:
        return float("nan")
    excess = returns - rf / trading_days
    downside = excess[excess < 0]
    s = downside.std(ddof=1) if len(downside) > 1 else 0.0
    if s == 0 or not np.isfinite(s):
        return float("nan")
    return float(excess.mean() / s * np.sqrt(trading_days))


def max_drawdown(equity: pd.Series):
    if equity.empty:
        return 0.0, None, None
    rolling_max = equity.cummax()
    dd = (equity - rolling_max) / rolling_max
    trough_ix = dd.idxmin()
    peak_ix = equity.loc[:trough_ix].idxmax()
    return float(dd.min()), peak_ix, trough_ix


def calmar(equity: pd.Series, trading_days: int = 252) -> float:
    mdd = abs(max_drawdown(equity)[0])
    if mdd == 0:
        return float("nan")
    return _safe_div(cagr(equity, trading_days), mdd)


def trade_stats(trades: Iterable) -> dict:
    rows = list(trades)
    if not rows:
        return dict(n_trades=0, hit_rate=float("nan"), profit_factor=float("nan"),
                    avg_pnl=float("nan"), median_pnl=float("nan"),
                    avg_winner=float("nan"), avg_loser=float("nan"),
                    avg_duration=float("nan"))
    pnls = np.array([float(t.net_pnl) for t in rows])
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    hit = float(len(wins) / len(pnls))
    pf = float(wins.sum() / -losses.sum()) if losses.size and losses.sum() < 0 else float("nan")
    durations = np.array([float(t.duration_days) for t in rows])
    return dict(
        n_trades=int(len(rows)),
        hit_rate=hit,
        profit_factor=pf,
        avg_pnl=float(pnls.mean()),
        median_pnl=float(np.median(pnls)),
        avg_winner=float(wins.mean()) if wins.size else float("nan"),
        avg_loser=float(losses.mean()) if losses.size else float("nan"),
        avg_duration=float(durations.mean()),
    )


def compute_metrics(
    equity: pd.Series,
    trades: list,
    initial_capital: float,
    open_count: pd.Series | None = None,
    exposure: pd.Series | None = None,
    trading_days: int = 252,
) -> dict:
    """Full metrics bundle. `equity` is a Series of total_equity over time."""
    eq = equity.dropna()
    rets = eq.pct_change().dropna()
    final = float(eq.iloc[-1]) if not eq.empty else float(initial_capital)
    pnl = final - initial_capital
    mdd, peak, trough = max_drawdown(eq)
    out = dict(
        initial_capital=float(initial_capital),
        final_equity=final,
        total_pnl=pnl,
        total_return_pct=float(pnl / initial_capital * 100) if initial_capital else float("nan"),
        cagr=cagr(eq, trading_days),
        ann_vol=annualised_vol(rets, trading_days),
        sharpe=sharpe(rets, trading_days=trading_days),
        sortino=sortino(rets, trading_days=trading_days),
        calmar=calmar(eq, trading_days),
        max_drawdown=mdd,
        max_dd_peak=peak.date().isoformat() if peak is not None and hasattr(peak, "date") else None,
        max_dd_trough=trough.date().isoformat() if trough is not None and hasattr(trough, "date") else None,
    )
    out.update(trade_stats(trades))
    if open_count is not None and not open_count.empty:
        out["avg_open_positions"] = float(open_count.mean())
        out["max_open_positions"] = int(open_count.max())
    if exposure is not None and not exposure.empty and initial_capital:
        out["avg_exposure_pct"] = float(exposure.mean() / initial_capital * 100)
        out["max_exposure_pct"] = float(exposure.max() / initial_capital * 100)
    return out


def underwater(equity: pd.Series) -> pd.Series:
    """Drawdown series in % from running peak."""
    return (equity / equity.cummax() - 1) * 100
