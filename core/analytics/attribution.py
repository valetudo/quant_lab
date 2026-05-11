"""Per-instrument / per-bucket P&L attribution."""

from __future__ import annotations

from typing import Iterable

import pandas as pd


def attribute_by_instrument(trades: Iterable) -> pd.DataFrame:
    """Aggregate net_pnl per single instrument across all trades (1- or N-leg)."""
    rows = []
    for t in trades:
        instruments = t.instruments
        sizes = t.sizes_eur
        # Distribute P&L proportionally to each leg's notional contribution.
        total_size = sum(abs(float(s)) for s in sizes) or 1.0
        for inst, size in zip(instruments, sizes):
            rows.append(
                dict(
                    instrument=inst,
                    pnl=float(t.net_pnl) * abs(float(size)) / total_size,
                    trade_id=getattr(t, "trade_id", None),
                )
            )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return (
        df.groupby("instrument", as_index=False)
        .agg(total_pnl=("pnl", "sum"), n_trades=("trade_id", "count"))
        .sort_values("total_pnl", ascending=False)
    )


def attribute_by_metadata_field(trades: Iterable, field: str) -> pd.DataFrame:
    """Aggregate net_pnl bucketed by a metadata field (e.g. exit_reason, sector)."""
    rows = []
    for t in trades:
        meta = t.metadata or {}
        rows.append(
            dict(
                bucket=meta.get(field, "n/a"),
                pnl=float(t.net_pnl),
                duration=float(t.duration_days),
            )
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return (
        df.groupby("bucket", as_index=False)
        .agg(
            total_pnl=("pnl", "sum"),
            n=("pnl", "count"),
            avg_pnl=("pnl", "mean"),
            avg_duration=("duration", "mean"),
        )
        .sort_values("total_pnl", ascending=False)
    )
