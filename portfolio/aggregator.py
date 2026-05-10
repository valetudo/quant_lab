"""Aggregate metrics_std.json + equity_std.csv across multiple strategies. Scaffold."""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd


def load_strategy_outputs(out_dir: str | Path) -> dict:
    """Return {strategy_id: {metrics, equity_df, trades_df}}."""
    p = Path(out_dir)
    out = {}
    for sub in p.iterdir():
        if not sub.is_dir():
            continue
        m_path = sub / "metrics_std.json"
        if not m_path.exists():
            continue
        metrics = json.loads(m_path.read_text(encoding="utf-8"))
        eq_path = sub / "equity_std.csv"
        tr_path = sub / "trades_std.csv"
        equity = pd.read_csv(eq_path) if eq_path.exists() else pd.DataFrame()
        trades = pd.read_csv(tr_path) if tr_path.exists() else pd.DataFrame()
        out[metrics.get("strategy_id", sub.name)] = dict(
            metrics=metrics, equity=equity, trades=trades,
        )
    return out


def combined_equity(strategy_outputs: dict, weights: dict[str, float]) -> pd.DataFrame:
    """Weighted sum of total_equity_eur across strategies; aligned on date."""
    frames = []
    for sid, w in weights.items():
        if sid not in strategy_outputs:
            continue
        eq = strategy_outputs[sid]["equity"].copy()
        if eq.empty:
            continue
        eq = eq[["date", "total_equity_eur"]].rename(
            columns={"total_equity_eur": f"eq_{sid}"})
        eq[f"eq_{sid}"] *= float(w)
        eq.set_index("date", inplace=True)
        frames.append(eq)
    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, axis=1).fillna(method="ffill").fillna(0)
    merged["total"] = merged.sum(axis=1)
    return merged
