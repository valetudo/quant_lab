"""Portfolio Overview — functional aggregate view across strategies.

Reads `outputs/{strategy}/{window}/equity_std.csv + metrics_std.json` for
each strategy listed in `configs/allocation.yaml`. The user runs each
strategy's backtest separately (via the Runner or CLI); this page
combines them.

A live re-run is offered for the two working strategies (bonds_income +
quality_stocks) within a single window.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yaml

# --- bootstrap ---
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PARENT = _PROJECT_ROOT.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))
# ---

from quant_lab.core.analytics.correlations import equity_correlation
from quant_lab.portfolio.aggregator import combined_equity, load_strategy_outputs
from quant_lab.portfolio.master_allocator import EqualWeightAllocator, FixedWeightAllocator

st.set_page_config(page_title="Portfolio Overview", page_icon="P", layout="wide")
st.title("Portfolio Overview")
st.caption("Multi-strategy aggregate. Reads per-strategy standard outputs.")

# --- allocation config --------------------------------------------------

alloc_path = _PROJECT_ROOT / "configs" / "allocation.yaml"
alloc_cfg = yaml.safe_load(alloc_path.read_text(encoding="utf-8")) if alloc_path.exists() else {}
weights_in = dict(alloc_cfg.get("allocation", {}))

col1, col2 = st.columns([2, 1])
with col1:
    st.subheader("Allocation")
    if weights_in:
        df_alloc = pd.DataFrame(
            [(k, v) for k, v in weights_in.items()],
            columns=["strategy", "weight"],
        )
        fig = px.pie(df_alloc, values="weight", names="strategy", hole=0.4,
                     title=None)
        fig.update_layout(template="plotly_white", height=260,
                          margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No allocations configured in `configs/allocation.yaml`.")

with col2:
    st.subheader("Weights")
    st.write(weights_in or "(empty)")
    st.caption("Edit `configs/allocation.yaml` to change.")

st.markdown("---")

# --- per-strategy outputs ------------------------------------------------

outputs_root = _PROJECT_ROOT / "outputs"
strategy_dirs = [d for d in outputs_root.glob("*") if d.is_dir()
                 and d.name in weights_in]
if not strategy_dirs:
    st.info(
        "No backtest outputs found for any allocated strategy.\n\n"
        "Run e.g. `python scripts/run_backtests.py --strategy quality_stocks "
        "--start 2022-01-01 --end 2024-12-31` first."
    )
    st.stop()

# Pick a window — let the user choose the most recent
windows: dict[str, list[Path]] = {}
for sd in strategy_dirs:
    wins = sorted([w for w in sd.iterdir() if w.is_dir()], reverse=True)
    if wins:
        windows[sd.name] = wins

if not windows:
    st.info("No completed backtests on disk.")
    st.stop()

# Intersect window names across strategies — for a meaningful combined chart
window_names = [{w.name for w in ws} for ws in windows.values()]
common_windows = sorted(set.intersection(*window_names), reverse=True) if window_names else []

if common_windows:
    chosen = st.selectbox("Window", common_windows, index=0)
else:
    st.warning("No common window across strategies. Showing most recent per strategy.")
    chosen = None

# Load outputs
outputs: dict = {}
for sid, ws in windows.items():
    target_w = None
    for w in ws:
        if chosen is None or w.name == chosen:
            target_w = w
            break
    if not target_w:
        continue
    try:
        metrics = json.loads((target_w / "metrics_std.json").read_text(encoding="utf-8"))
    except Exception:
        continue
    try:
        equity = pd.read_csv(target_w / "equity_std.csv", parse_dates=["date"])
    except Exception:
        equity = pd.DataFrame()
    try:
        trades = pd.read_csv(target_w / "trades_std.csv")
    except Exception:
        trades = pd.DataFrame()
    outputs[sid] = dict(metrics=metrics, equity=equity, trades=trades)

if not outputs:
    st.error("Could not load any strategy outputs.")
    st.stop()

# --- combined equity ----------------------------------------------------

combined = combined_equity(outputs, weights_in)
st.subheader("Combined equity")
if combined.empty:
    st.warning("Empty combined equity.")
else:
    combined.index = pd.to_datetime(combined.index)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=combined.index, y=combined["total"],
                             mode="lines", name="Portfolio", line=dict(width=2)))
    for col in combined.columns:
        if col.startswith("eq_"):
            sid = col[3:]
            fig.add_trace(go.Scatter(x=combined.index, y=combined[col],
                                     mode="lines", name=sid,
                                     line=dict(width=1, dash="dot"),
                                     opacity=0.7))
    fig.update_layout(template="plotly_white", height=420,
                      yaxis_title="EUR (weighted)")
    st.plotly_chart(fig, use_container_width=True)

# --- metrics side by side -----------------------------------------------

st.subheader("Metrics per strategy")
metrics_rows = []
for sid, o in outputs.items():
    m = o["metrics"]
    metrics_rows.append(dict(
        strategy=sid, weight=weights_in.get(sid, 0),
        sharpe=m.get("sharpe"),
        sortino=m.get("sortino"),
        max_dd=m.get("max_drawdown"),
        total_return_pct=m.get("total_return_pct"),
        n_trades=m.get("n_trades"),
        final_equity=m.get("final_equity"),
    ))
st.dataframe(pd.DataFrame(metrics_rows), use_container_width=True, hide_index=True)

# --- correlation matrix -------------------------------------------------

st.subheader("Cross-strategy correlation")
eq_series = {}
for sid, o in outputs.items():
    if o["equity"].empty or "total_equity_eur" not in o["equity"].columns:
        continue
    eq = o["equity"].set_index("date")["total_equity_eur"]
    eq_series[sid] = eq

if len(eq_series) >= 2:
    corr = equity_correlation(eq_series)
    if not corr.empty:
        fig_corr = px.imshow(corr, text_auto=".2f", aspect="auto",
                             color_continuous_scale="RdBu_r", zmin=-1, zmax=1)
        fig_corr.update_layout(template="plotly_white", height=320,
                               title=None)
        st.plotly_chart(fig_corr, use_container_width=True)
    else:
        st.info("Not enough overlapping data for correlation.")
else:
    st.info("Need >=2 strategies with output data for correlation.")

# --- attribution --------------------------------------------------------

st.subheader("P&L attribution")
attr_rows = []
for sid, o in outputs.items():
    m = o["metrics"]
    w = weights_in.get(sid, 0.0)
    pnl_strat = m.get("total_pnl") or 0.0
    pnl_attrib = pnl_strat * w
    attr_rows.append(dict(strategy=sid, weight=w, raw_pnl=pnl_strat,
                          weighted_contribution=pnl_attrib))
attr_df = pd.DataFrame(attr_rows)
if not attr_df.empty:
    fig_attr = px.bar(attr_df, x="strategy", y="weighted_contribution",
                      hover_data=["weight", "raw_pnl"],
                      title=None)
    fig_attr.update_layout(template="plotly_white", height=260,
                           yaxis_title="EUR contribution")
    st.plotly_chart(fig_attr, use_container_width=True)
    st.dataframe(attr_df, use_container_width=True, hide_index=True)

# --- walk-forward verdict badges ---------------------------------------

st.subheader("Walk-forward verdicts")
for sid in weights_in:
    wf_path = _PROJECT_ROOT / "outputs" / sid / "walk_forward_verdict.json"
    if not wf_path.exists():
        continue
    try:
        wf = json.loads(wf_path.read_text(encoding="utf-8"))
    except Exception:
        continue
    v = wf["summary"]["verdict"]
    med = wf["summary"]["median_sharpe_oos"]
    color = {"ROBUST": "green", "MARGINAL": "orange",
             "OVERFIT": "red"}.get(v, "gray")
    st.markdown(
        f"<div style='padding:6px 14px;margin:4px 0;border-radius:6px;"
        f"background-color:{color};color:white;display:inline-block;'>"
        f"<b>{sid}</b>: {v}  |  median Sharpe OOS = {med:.3f}"
        f"</div>",
        unsafe_allow_html=True,
    )
