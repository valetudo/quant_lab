"""Equity curve chart (Plotly)."""
from __future__ import annotations
import pandas as pd
import plotly.graph_objects as go


def equity_chart(equity: pd.Series, *, title: str = "Equity curve") -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=equity.index, y=equity.values,
        mode="lines", name="equity_eur", line=dict(width=2),
    ))
    fig.update_layout(
        title=title, xaxis_title="date", yaxis_title="EUR",
        template="plotly_white", height=400,
    )
    return fig
