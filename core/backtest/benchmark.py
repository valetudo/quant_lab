"""Buy-and-hold benchmark utilities — SPY-style passive comparison.

Provides a single-symbol passive backtest (no rebalance, no costs) plus
helpers for alpha-style comparisons against an active strategy's equity
curve. Used throughout the UI to show side-by-side V5 vs SPY visuals.

The benchmark price source is the existing parquet tree at
``data_storage/prices/`` (via ``DataStorage.get_prices``). Dividends and
splits are baked into ``adj_close``, so a naive equity = capital × (px /
px[0]) is total-return-correct.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from core.data.storage import DataStorage, load_global_config


@dataclass
class BenchmarkResult:
    """Buy-and-hold benchmark output. All metrics are total-return based."""

    symbol: str
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    initial_capital_eur: float
    final_equity_eur: float
    daily_equity: pd.Series  # date-indexed equity in EUR
    total_return_pct: float
    cagr: float  # decimal (0.12 == 12 %)
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown: float  # decimal, negative
    annualized_vol: float  # decimal
    max_dd_peak: Optional[pd.Timestamp] = None
    max_dd_trough: Optional[pd.Timestamp] = None


def _safe_div(a: float, b: float) -> float:
    return float(a / b) if b not in (0, 0.0) and np.isfinite(b) else float("nan")


class Benchmark:
    """Buy-and-hold benchmark.

    ``run(start, end, capital)`` returns a ``BenchmarkResult`` with the
    same metric definitions as ``core.analytics.metrics`` — Sharpe,
    Sortino, Calmar, max drawdown, annual vol.
    """

    def __init__(self, symbol: str = "SPY", storage: Optional[DataStorage] = None) -> None:
        self.symbol = symbol
        self.storage = storage or DataStorage.from_config(load_global_config())

    def run(
        self,
        start: pd.Timestamp | date | str,
        end: pd.Timestamp | date | str,
        initial_capital_eur: float = 100_000.0,
    ) -> BenchmarkResult:
        start_ts = pd.to_datetime(start)
        end_ts = pd.to_datetime(end)
        df = self.storage.get_prices(self.symbol, start_ts, end_ts)
        if df is None or df.empty:
            raise ValueError(
                f"no price data for benchmark {self.symbol!r} in "
                f"[{start_ts.date()}, {end_ts.date()}] — has the FMP "
                "migration run for that symbol?"
            )
        if "adj_close" not in df.columns:
            raise ValueError(f"price frame for {self.symbol} has no adj_close column")

        px = df["adj_close"].astype(float)
        if px.iloc[0] <= 0:
            raise ValueError(f"first price for {self.symbol} is non-positive")

        equity = initial_capital_eur * (px / px.iloc[0])
        equity.name = self.symbol
        rets = equity.pct_change().dropna()

        n_days = (px.index[-1] - px.index[0]).days
        n_years = n_days / 365.25 if n_days > 0 else 0.0
        total_return = float(equity.iloc[-1] / initial_capital_eur - 1.0)
        cagr = (
            float((equity.iloc[-1] / initial_capital_eur) ** (1.0 / n_years) - 1.0)
            if n_years > 0
            else float("nan")
        )

        ann_vol = float(rets.std(ddof=1) * np.sqrt(252)) if len(rets) > 1 else 0.0
        sharpe = _safe_div(rets.mean() * 252, ann_vol) if ann_vol > 0 else float("nan")
        downside = rets[rets < 0]
        downside_vol = float(downside.std(ddof=1) * np.sqrt(252)) if len(downside) > 1 else 0.0
        sortino = _safe_div(rets.mean() * 252, downside_vol) if downside_vol > 0 else float("nan")

        rolling_max = equity.cummax()
        dd = equity / rolling_max - 1.0
        max_dd = float(dd.min()) if not dd.empty else 0.0
        trough = dd.idxmin() if not dd.empty else None
        peak = equity.loc[:trough].idxmax() if trough is not None else None
        calmar = _safe_div(cagr, abs(max_dd)) if max_dd < 0 else float("nan")

        return BenchmarkResult(
            symbol=self.symbol,
            start_date=px.index[0],
            end_date=px.index[-1],
            initial_capital_eur=float(initial_capital_eur),
            final_equity_eur=float(equity.iloc[-1]),
            daily_equity=equity,
            total_return_pct=total_return * 100,
            cagr=cagr,
            sharpe=sharpe,
            sortino=sortino,
            calmar=calmar,
            max_drawdown=max_dd,
            annualized_vol=ann_vol,
            max_dd_peak=peak,
            max_dd_trough=trough,
        )


# ---------------------------------------------------------------------------
# Alpha / excess-return helpers
# ---------------------------------------------------------------------------


def align_equities(
    strategy_equity: pd.Series,
    benchmark_equity: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Forward-fill both series onto their union of dates so they align."""
    idx = strategy_equity.index.union(benchmark_equity.index).sort_values()
    s = strategy_equity.reindex(idx).ffill()
    b = benchmark_equity.reindex(idx).ffill()
    common = s.dropna().index.intersection(b.dropna().index)
    return s.loc[common], b.loc[common]


def compute_excess_return(
    strategy_equity: pd.Series,
    benchmark_equity: pd.Series,
) -> pd.Series:
    """Daily log-return excess of strategy over benchmark."""
    s, b = align_equities(strategy_equity, benchmark_equity)
    return (np.log(s / s.shift(1)) - np.log(b / b.shift(1))).dropna()


def compute_cumulative_alpha(
    strategy_equity: pd.Series,
    benchmark_equity: pd.Series,
) -> pd.Series:
    """Cumulative compounded excess return as a daily series."""
    excess = compute_excess_return(strategy_equity, benchmark_equity)
    return excess.cumsum().apply(np.exp) - 1.0


def compute_rolling_alpha(
    strategy_equity: pd.Series,
    benchmark_equity: pd.Series,
    window_days: int = 252,
) -> pd.Series:
    """Rolling N-day sum of daily excess log-returns (≈ cumulative N-day alpha)."""
    excess = compute_excess_return(strategy_equity, benchmark_equity)
    return excess.rolling(window_days).sum()


def calendar_year_returns(equity: pd.Series) -> pd.DataFrame:
    """Year-by-year total return based on the December-31 equity values."""
    if equity is None or equity.empty:
        return pd.DataFrame(columns=["year", "return_pct", "end_equity"])
    eq = equity.copy()
    eq.index = pd.to_datetime(eq.index)
    yearly = eq.resample("YE").last()
    # Prepend the start-of-window equity so the first year's % return is well-defined
    pre = pd.Series([eq.iloc[0]], index=[eq.index[0] - pd.Timedelta(days=1)])
    yearly = pd.concat([pre, yearly])
    pct = yearly.pct_change() * 100
    df = (
        pd.DataFrame(
            {
                "year": yearly.index.year,
                "return_pct": pct.values,
                "end_equity": yearly.values,
            }
        )
        .dropna(subset=["return_pct"])
        .reset_index(drop=True)
    )
    df["year"] = df["year"].astype(int)
    return df


def alpha_summary(
    strategy_equity: pd.Series,
    benchmark_equity: pd.Series,
) -> dict:
    """One-shot summary: CAGR delta, Sharpe delta, max-DD delta, calendar-year wins."""
    s, b = align_equities(strategy_equity, benchmark_equity)
    if s.empty or b.empty:
        return {}
    n_days = (s.index[-1] - s.index[0]).days
    n_years = n_days / 365.25 if n_days > 0 else 0.0

    def _cagr(eq):
        return (
            ((eq.iloc[-1] / eq.iloc[0]) ** (1.0 / n_years) - 1.0) if n_years > 0 else float("nan")
        )

    def _sharpe(eq):
        r = eq.pct_change().dropna()
        if len(r) < 2:
            return float("nan")
        sd = r.std(ddof=1)
        return float(r.mean() / sd * np.sqrt(252)) if sd > 0 else float("nan")

    def _max_dd(eq):
        rm = eq.cummax()
        return float((eq / rm - 1.0).min())

    sy_cy = calendar_year_returns(s)
    bk_cy = calendar_year_returns(b)
    cy = sy_cy.merge(bk_cy, on="year", suffixes=("_strategy", "_benchmark"))
    cy["alpha_pct"] = cy["return_pct_strategy"] - cy["return_pct_benchmark"]
    cy["win"] = cy["alpha_pct"] > 0
    wins = int(cy["win"].sum())
    total = int(len(cy))

    return {
        "strategy_cagr": _cagr(s),
        "benchmark_cagr": _cagr(b),
        "annualized_alpha": _cagr(s) - _cagr(b),
        "strategy_sharpe": _sharpe(s),
        "benchmark_sharpe": _sharpe(b),
        "sharpe_delta": _sharpe(s) - _sharpe(b),
        "strategy_max_dd": _max_dd(s),
        "benchmark_max_dd": _max_dd(b),
        "calendar_year_wins": wins,
        "calendar_year_total": total,
        "calendar_year_win_rate": wins / total if total > 0 else 0.0,
        "calendar_year_table": cy.to_dict("records"),
    }


def classify_outperformance(summary: dict) -> str:
    """Return one of: 'significant', 'marginal', 'underperform'."""
    alpha = summary.get("annualized_alpha")
    sh_d = summary.get("sharpe_delta")
    if alpha is None or sh_d is None or pd.isna(alpha) or pd.isna(sh_d):
        return "insufficient_data"
    if alpha > 0.02 and sh_d > 0.20:
        return "significant"
    if alpha > 0 and sh_d > 0:
        return "marginal"
    return "underperform"
