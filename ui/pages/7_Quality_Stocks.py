"""Quality Stocks — dedicated dashboard.

Form: window + parameter overrides + costs.
Outputs: equity curve vs SPY benchmark, drawdown, top picks, walk-forward badge.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# --- bootstrap ---
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PARENT = _PROJECT_ROOT.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))
# ---

from quant_lab.core.analytics.metrics import compute_metrics
from quant_lab.core.backtest.engine import PortfolioBacktester
from quant_lab.core.data.providers.fmp_provider import FMPProvider
from quant_lab.core.io.standard_schema import write_standard_outputs
from quant_lab.core.data.storage import DataStorage, load_global_config
from quant_lab.strategies.quality_stocks import QualityStocks
from quant_lab.strategies.quality_stocks.runner import build_panel
from quant_lab.ui.components.equity_chart import equity_chart
from quant_lab.ui.components.metrics_table import metrics_table


st.set_page_config(page_title="Quality Stocks", page_icon="*", layout="wide")
st.title("Quality Stocks")
st.caption("Long-only S&P 500 quality + momentum, monthly rebalance, bond fallback.")


# --- walk-forward verdict badge -----------------------------------------

wf_path = _PROJECT_ROOT / "outputs" / "quality_stocks" / "walk_forward_verdict.json"
if wf_path.exists():
    try:
        wf = json.loads(wf_path.read_text(encoding="utf-8"))
        verdict = wf["summary"]["verdict"]
        med = wf["summary"]["median_sharpe_oos"]
        color = {"ROBUST": "green", "MARGINAL": "orange", "OVERFIT": "red"}.get(verdict, "gray")
        st.markdown(
            f"<div style='padding:8px 16px;border-radius:6px;"
            f"background-color:{color};color:white;display:inline-block;'>"
            f"<b>Walk-forward verdict: {verdict}</b>  |  median Sharpe OOS = {med:.3f}"
            f"  |  {wf['summary']['n_folds']} folds"
            f"</div>",
            unsafe_allow_html=True,
        )
    except Exception as e:
        st.warning(f"could not load walk-forward verdict: {e}")
else:
    st.info("Walk-forward verdict not yet computed. "
            "Run `python scripts/run_quality_walk_forward.py`.")


# --- run-form -----------------------------------------------------------

with st.expander("Run a backtest", expanded=True):
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        start = st.date_input("Start", value=date(2022, 1, 3), key="qs_start")
    with c2:
        end = st.date_input("End", value=date(2024, 12, 31), key="qs_end")
    with c3:
        capital = st.number_input("Capital (EUR)", value=100_000.0,
                                  min_value=1000.0, step=10_000.0, key="qs_cap")
    c4, c5 = st.columns(2)
    with c4:
        commission_bps = st.number_input("Commission (bps)", value=5.0, key="qs_comm")
    with c5:
        slippage_bps = st.number_input("Slippage (bps)", value=5.0, key="qs_slip")

    run = st.button("Run", type="primary", key="qs_run")

if run:
    cfg = load_global_config()
    storage = DataStorage.from_config(cfg)
    fmp = FMPProvider()
    with st.spinner("Building panel..."):
        universe = fmp.get_index_constituents("sp500")
        panel = build_panel(storage, start=start, end=end,
                            universe_symbols=universe, extra=("SPY", "IEF"))
    if panel.empty:
        st.error("Empty panel — run `scripts/migrate_prices_to_fmp.py` to populate prices.")
        st.stop()
    st.caption(f"panel: {panel.shape[0]} bars × {panel.shape[1]} symbols")

    with st.spinner("Running backtest..."):
        strat = QualityStocks(fmp=fmp, prefetch=False)
        bt = PortfolioBacktester(strat, panel, initial_capital_eur=capital,
                                 commission_bps=commission_bps, slippage_bps=slippage_bps)
        res = bt.run()

    eq = res.equity["equity"] if not res.equity.empty else pd.Series(dtype=float)
    metrics = compute_metrics(eq, res.trades, capital,
                              open_count=res.open_count, exposure=res.exposure)

    # SPY benchmark
    spy = panel["SPY"] if "SPY" in panel.columns else pd.Series(dtype=float)
    if not spy.empty:
        spy_norm = (spy / spy.iloc[0]) * capital
    else:
        spy_norm = None

    # --- equity + benchmark chart
    fig = go.Figure()
    if not eq.empty:
        fig.add_trace(go.Scatter(x=eq.index, y=eq.values, mode="lines",
                                 name="Quality Stocks", line=dict(width=2)))
    if spy_norm is not None:
        fig.add_trace(go.Scatter(x=spy_norm.index, y=spy_norm.values, mode="lines",
                                 name="SPY (normalised)",
                                 line=dict(width=1, dash="dash")))
    fig.update_layout(template="plotly_white", height=400, title="Equity vs SPY",
                      yaxis_title="EUR")
    st.plotly_chart(fig, use_container_width=True)

    # --- drawdown
    if not eq.empty:
        dd = (eq / eq.cummax() - 1) * 100
        fig_dd = go.Figure()
        fig_dd.add_trace(go.Scatter(x=dd.index, y=dd.values, fill="tozeroy",
                                    line=dict(width=1, color="crimson"),
                                    name="drawdown %"))
        fig_dd.update_layout(template="plotly_white", height=240,
                             title="Drawdown (%)", yaxis_title="%")
        st.plotly_chart(fig_dd, use_container_width=True)

    # --- metrics + outputs
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Metrics")
        metrics_table(metrics)
    with c2:
        st.subheader("Trades")
        if res.trades:
            trades_df = pd.DataFrame([{
                "entry": t.entry_date, "exit": t.exit_date,
                "symbol": t.instruments[0] if t.instruments else "",
                "net_pnl": t.net_pnl, "duration_d": t.duration_days,
                "reason": t.exit_reason,
            } for t in res.trades])
            st.dataframe(trades_df.sort_values("entry"), use_container_width=True,
                         hide_index=True, height=400)
        else:
            st.info("No trades closed in window.")

    # Persist standard outputs
    out_dir = _PROJECT_ROOT / "outputs" / "quality_stocks" / f"{start}_{end}"
    paths = write_standard_outputs(
        out_dir,
        strategy_id="quality_stocks",
        universe="sp500", currency="EUR",
        trades=res.trades, equity=res.equity, open_count=res.open_count,
        metrics=metrics, period_start=start, period_end=end,
    )
    st.caption(f"outputs -> {out_dir}")
