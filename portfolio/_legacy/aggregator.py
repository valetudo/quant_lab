"""Aggregate N strategies into one portfolio with allocator-driven weights.

Each strategy runs INDEPENDENTLY with its allocated slice of capital.
Equity curves are summed (weighted), trades are pooled, correlation is
computed pairwise on daily returns.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date as date_type
from pathlib import Path
from typing import Optional, Sequence

import pandas as pd

from core.analytics.metrics import compute_metrics
from core.backtest.engine import PortfolioBacktester
from core.strategy.base import Strategy
from portfolio._legacy.master_allocator import EqualWeightAllocator, MasterAllocator

log = logging.getLogger(__name__)


@dataclass
class StrategyRunResult:
    strategy_id: str
    equity: pd.DataFrame
    trades: list
    metrics: dict
    capital_alloc: float
    open_count: Optional[pd.Series] = None
    exposure: Optional[pd.Series] = None


@dataclass
class PortfolioResult:
    strategy_results: dict[str, StrategyRunResult] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)
    portfolio_equity: pd.Series = field(default_factory=pd.Series)
    portfolio_metrics: dict = field(default_factory=dict)
    correlations: pd.DataFrame = field(default_factory=pd.DataFrame)


class PortfolioAggregator:
    """Multi-strategy backtest with allocator-driven capital split."""

    def __init__(
        self,
        strategies: Sequence[Strategy],
        panels: dict[str, pd.DataFrame],
        *,
        total_capital_eur: float = 100_000.0,
        allocator: Optional[MasterAllocator] = None,
        commission_bps: float = 5.0,
        slippage_bps: float = 5.0,
    ) -> None:
        if not strategies:
            raise ValueError("at least one strategy required")
        self.strategies = list(strategies)
        # panels[strategy_id] -> wide DataFrame for that strategy's engine
        self.panels = dict(panels)
        self.total_capital = float(total_capital_eur)
        self.commission_bps = commission_bps
        self.slippage_bps = slippage_bps
        self.allocator = allocator or EqualWeightAllocator([s.strategy_id for s in self.strategies])

    # ---- main run -----------------------------------------------------

    def run(
        self, start: Optional[date_type] = None, end: Optional[date_type] = None
    ) -> PortfolioResult:
        weights = self.allocator.compute_weights(
            pd.Timestamp(start) if start else pd.Timestamp.today(),
            strategy_states={},
            market_data=None,
        )
        result = PortfolioResult(weights=dict(weights))

        for strat in self.strategies:
            sid = strat.strategy_id
            if sid not in self.panels:
                log.warning("no panel for strategy %s — skipping", sid)
                continue
            panel = self.panels[sid]
            if panel.empty:
                log.warning("panel empty for %s — skipping", sid)
                continue
            cap = self.total_capital * float(weights.get(sid, 0.0))
            if cap <= 0:
                continue
            # If the strategy carries its own initial_capital_eur config, override
            if hasattr(strat, "_initial_capital_eur"):
                try:
                    strat._initial_capital_eur = cap
                except Exception:
                    pass
            bt = PortfolioBacktester(
                strat,
                panel,
                initial_capital_eur=cap,
                commission_bps=self.commission_bps,
                slippage_bps=self.slippage_bps,
            )
            res = bt.run()
            eq = res.equity["equity"] if not res.equity.empty else pd.Series(dtype=float)
            metrics = compute_metrics(
                eq, res.trades, cap, open_count=res.open_count, exposure=res.exposure
            )
            result.strategy_results[sid] = StrategyRunResult(
                strategy_id=sid,
                equity=res.equity,
                trades=res.trades,
                metrics=metrics,
                capital_alloc=cap,
                open_count=res.open_count,
                exposure=res.exposure,
            )

        # Aggregate equity (forward-fill per-strategy to common index, then sum)
        eq_frames = {}
        for sid, sr in result.strategy_results.items():
            if sr.equity.empty:
                continue
            eq = sr.equity["equity"].copy()
            eq.name = sid
            eq_frames[sid] = eq
        if eq_frames:
            df = pd.concat(eq_frames, axis=1).ffill()
            # For dates before a strategy starts producing equity, fall back
            # to its capital allocation
            for sid, sr in result.strategy_results.items():
                if sid in df.columns:
                    df[sid] = df[sid].fillna(sr.capital_alloc)
            result.portfolio_equity = df.sum(axis=1)
            result.portfolio_equity.name = "portfolio_equity"

            # Aggregate metrics on the combined curve
            result.portfolio_metrics = compute_metrics(
                result.portfolio_equity,
                trades=[t for sr in result.strategy_results.values() for t in sr.trades],
                initial_capital=self.total_capital,
            )

            # Pairwise correlation on daily returns
            rets = df.pct_change().dropna(how="all")
            result.correlations = rets.corr() if not rets.empty else pd.DataFrame()

        return result

    # ---- helpers -----------------------------------------------------

    @staticmethod
    def save_summary(result: PortfolioResult, dest: str | Path) -> Path:
        p = Path(dest)
        p.parent.mkdir(parents=True, exist_ok=True)
        summary = {
            "weights": result.weights,
            "portfolio_metrics": result.portfolio_metrics,
            "per_strategy_metrics": {
                sid: sr.metrics for sid, sr in result.strategy_results.items()
            },
            "correlations": result.correlations.to_dict() if not result.correlations.empty else {},
        }
        p.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        return p


def load_strategy_outputs(
    out_dir: str | Path,
    *,
    window: Optional[str] = None,
) -> dict:
    """Read per-strategy standard outputs from disk.

    Supports two layouts:
      - flat:    <out_dir>/<strategy_id>/{metrics_std.json, ...}
      - nested:  <out_dir>/<strategy_id>/<window>/{metrics_std.json, ...}

    If `window` is given, picks that subdirectory. Otherwise picks the
    most recent (alphabetically sorted descending — ISO date naming).
    """
    p = Path(out_dir)
    out: dict = {}
    if not p.exists():
        return out

    def _load(metrics_dir: Path) -> Optional[dict]:
        m_path = metrics_dir / "metrics_std.json"
        if not m_path.exists():
            return None
        try:
            metrics = json.loads(m_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        eq_path = metrics_dir / "equity_std.csv"
        tr_path = metrics_dir / "trades_std.csv"
        equity = pd.read_csv(eq_path) if eq_path.exists() else pd.DataFrame()
        trades = pd.read_csv(tr_path) if tr_path.exists() else pd.DataFrame()
        return dict(metrics=metrics, equity=equity, trades=trades)

    for sub in p.iterdir():
        if not sub.is_dir():
            continue
        # Flat layout?
        d = _load(sub)
        if d is not None:
            out[d["metrics"].get("strategy_id", sub.name)] = d
            continue
        # Nested layout — pick window subdirectory
        windows = sorted([w for w in sub.iterdir() if w.is_dir()], reverse=True)
        if not windows:
            continue
        if window is not None:
            chosen = next((w for w in windows if w.name == window), None)
        else:
            chosen = windows[0]
        if chosen is None:
            continue
        d = _load(chosen)
        if d is not None:
            out[d["metrics"].get("strategy_id", sub.name)] = d
    return out


def combined_equity(strategy_outputs: dict, weights: dict[str, float]) -> pd.DataFrame:
    """Weighted sum of total_equity_eur across strategies; aligned on date.

    Kept for backwards-compat with Phase 1 callers.
    """
    frames = []
    for sid, w in weights.items():
        if sid not in strategy_outputs:
            continue
        eq = strategy_outputs[sid]["equity"].copy()
        if eq.empty:
            continue
        eq = eq[["date", "total_equity_eur"]].rename(columns={"total_equity_eur": f"eq_{sid}"})
        eq[f"eq_{sid}"] *= float(w)
        eq.set_index("date", inplace=True)
        frames.append(eq)
    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, axis=1).ffill().fillna(0)
    merged["total"] = merged.sum(axis=1)
    return merged
