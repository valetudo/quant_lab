"""Metrics summary table."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def metrics_table(metrics: dict) -> None:
    rows = []
    pct_keys = {
        "total_return_pct",
        "cagr",
        "ann_vol",
        "max_drawdown",
        "hit_rate",
        "avg_exposure_pct",
        "max_exposure_pct",
    }
    for k, v in metrics.items():
        if k.startswith("_"):
            continue
        if isinstance(v, float):
            if k in pct_keys:
                rows.append((k, f"{v * 100:.2f}%" if abs(v) < 1.5 else f"{v:.2f}%"))
            else:
                rows.append((k, f"{v:.2f}"))
        else:
            rows.append((k, str(v) if v is not None else "—"))
    df = pd.DataFrame(rows, columns=["metric", "value"])
    st.dataframe(df, use_container_width=True, hide_index=True)
