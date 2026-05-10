"""Cross-strategy standard schema for trades / equity / metrics.

Generalized from pair_trading_ITA: every strategy in quant_lab writes its
backtest outputs with this exact column set so the portfolio aggregator
and dashboard can read N strategies uniformly.

Outputs land as `trades_std.csv`, `equity_std.csv`, `metrics_std.json`.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Sequence

import pandas as pd


STANDARD_TRADE_COLUMNS = [
    "trade_id",
    "strategy_id",
    "entry_date",
    "exit_date",
    "instruments",       # JSON list
    "sides",             # JSON list of 'long'/'short' aligned to instruments
    "sizes_eur",         # JSON list aligned to instruments
    "entry_prices",      # JSON list aligned to instruments
    "exit_prices",       # JSON list aligned to instruments
    "gross_pnl_eur",
    "costs_eur",
    "net_pnl_eur",
    "duration_days",
    "exit_reason",
    "metadata_json",
]

STANDARD_EQUITY_COLUMNS = [
    "date", "cash_eur", "positions_value_eur", "total_equity_eur", "n_open_positions",
]

STANDARD_METRICS_KEYS = [
    "strategy_id", "universe", "currency", "period_start", "period_end",
    "initial_capital", "final_equity", "total_pnl", "total_return_pct",
    "cagr", "ann_vol", "sharpe", "sortino", "calmar", "max_drawdown",
    "max_dd_peak", "max_dd_trough", "n_trades", "hit_rate", "profit_factor",
    "avg_pnl", "median_pnl", "avg_winner", "avg_loser",
    "avg_duration_days", "avg_open_positions", "avg_exposure_pct",
]


def trade_to_standard(trade, strategy_id: str) -> dict:
    """Map an engine `Trade` (see core.backtest.portfolio) to one STANDARD_TRADE_COLUMNS row."""
    return {
        "trade_id":      trade.trade_id if getattr(trade, "trade_id", None) else str(uuid.uuid4()),
        "strategy_id":   strategy_id,
        "entry_date":    trade.entry_date.isoformat() if hasattr(trade.entry_date, "isoformat") else str(trade.entry_date),
        "exit_date":     trade.exit_date.isoformat() if hasattr(trade.exit_date, "isoformat") else str(trade.exit_date),
        "instruments":   json.dumps(list(trade.instruments)),
        "sides":         json.dumps(list(trade.sides)),
        "sizes_eur":     json.dumps([round(float(s), 2) for s in trade.sizes_eur]),
        "entry_prices":  json.dumps([round(float(p), 4) for p in trade.entry_prices]),
        "exit_prices":   json.dumps([round(float(p), 4) for p in trade.exit_prices]),
        "gross_pnl_eur": round(float(trade.gross_pnl), 2),
        "costs_eur":     round(float(trade.costs), 2),
        "net_pnl_eur":   round(float(trade.net_pnl), 2),
        "duration_days": int(trade.duration_days),
        "exit_reason":   str(trade.exit_reason),
        "metadata_json": json.dumps(trade.metadata or {}, default=str),
    }


def equity_to_standard(eq_df: pd.DataFrame, open_count: pd.Series | None = None) -> pd.DataFrame:
    """Map an engine equity DataFrame (cash/locked/equity columns) to STANDARD_EQUITY_COLUMNS."""
    if open_count is None:
        n_open = [0] * len(eq_df)
    else:
        n_open = open_count.reindex(eq_df.index).fillna(0).astype(int).tolist()
    return pd.DataFrame({
        "date":                [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
                                for d in eq_df.index],
        "cash_eur":            eq_df["cash"].astype(float).tolist(),
        "positions_value_eur": eq_df["locked"].astype(float).tolist(),
        "total_equity_eur":    eq_df["equity"].astype(float).tolist(),
        "n_open_positions":    n_open,
    })


def metrics_to_standard(metrics: dict, *, strategy_id: str, universe: str,
                        currency: str, period_start, period_end) -> dict:
    out = {
        "strategy_id":         strategy_id,
        "universe":            universe,
        "currency":            currency,
        "period_start":        str(period_start),
        "period_end":          str(period_end),
        "initial_capital":     metrics.get("initial_capital"),
        "final_equity":        metrics.get("final_equity"),
        "total_pnl":           metrics.get("total_pnl"),
        "total_return_pct":    metrics.get("total_return_pct"),
        "cagr":                metrics.get("cagr"),
        "ann_vol":             metrics.get("ann_vol"),
        "sharpe":              metrics.get("sharpe"),
        "sortino":             metrics.get("sortino"),
        "calmar":              metrics.get("calmar"),
        "max_drawdown":        metrics.get("max_drawdown"),
        "max_dd_peak":         metrics.get("max_dd_peak"),
        "max_dd_trough":       metrics.get("max_dd_trough"),
        "n_trades":            metrics.get("n_trades"),
        "hit_rate":            metrics.get("hit_rate"),
        "profit_factor":       metrics.get("profit_factor"),
        "avg_pnl":             metrics.get("avg_pnl"),
        "median_pnl":          metrics.get("median_pnl"),
        "avg_winner":          metrics.get("avg_winner"),
        "avg_loser":           metrics.get("avg_loser"),
        "avg_duration_days":   metrics.get("avg_duration"),
        "avg_open_positions":  metrics.get("avg_open_positions"),
        "avg_exposure_pct":    metrics.get("avg_exposure_pct"),
        "_generated_at":       datetime.utcnow().isoformat(),
    }
    return out


def write_standard_outputs(
    out_dir: str | Path,
    *,
    strategy_id: str,
    universe: str,
    currency: str,
    trades: Sequence,
    equity: pd.DataFrame,
    open_count: pd.Series | None,
    metrics: dict,
    period_start,
    period_end,
) -> dict[str, Path]:
    """Write trades_std.csv + equity_std.csv + metrics_std.json into `out_dir`."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    trade_rows = [trade_to_standard(t, strategy_id) for t in trades]
    trades_df = pd.DataFrame(trade_rows, columns=STANDARD_TRADE_COLUMNS)
    trades_path = out / "trades_std.csv"
    trades_df.to_csv(trades_path, index=False)

    equity_df = equity_to_standard(equity, open_count)
    equity_path = out / "equity_std.csv"
    equity_df.to_csv(equity_path, index=False)

    metrics_std = metrics_to_standard(
        metrics, strategy_id=strategy_id, universe=universe, currency=currency,
        period_start=period_start, period_end=period_end,
    )
    metrics_path = out / "metrics_std.json"
    metrics_path.write_text(json.dumps(metrics_std, indent=2, default=str), encoding="utf-8")

    return {"trades": trades_path, "equity": equity_path, "metrics": metrics_path}
