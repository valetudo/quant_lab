"""Shared helpers for streamlit pages that run streaming backtests.

Encapsulates the Live-mode flow so both Backtest Runner and Quality Stocks pages
can reuse it without duplicating the threading + polling boilerplate.
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.backtest.engine import BacktestResult, PortfolioBacktester
from core.backtest.streaming import StreamReader, StreamWriter


def new_run_id() -> str:
    return uuid.uuid4().hex[:8]


def stream_dir(repo_root: Path) -> Path:
    p = repo_root / "outputs" / "_streams"
    p.mkdir(parents=True, exist_ok=True)
    return p


def start_live_run(
    *,
    state_key: str,
    repo_root: Path,
    strategy,
    panel: pd.DataFrame,
    initial_capital_eur: float,
    commission_bps: float,
    slippage_bps: float,
) -> str:
    """Launch a backtest in a daemon thread; record handles in session_state.

    `state_key` is a unique prefix (e.g. "br" for backtest runner, "qs" for
    quality stocks) so multiple pages can coexist without colliding.
    """
    run_id = new_run_id()
    out_dir = stream_dir(repo_root)
    writer = StreamWriter(run_id, out_dir)
    bt = PortfolioBacktester(
        strategy,
        panel,
        initial_capital_eur=initial_capital_eur,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
        stream_writer=writer,
    )
    holder: dict = {"res": None, "err": None}

    def _worker():
        try:
            holder["res"] = bt.run()
        except Exception as e:
            holder["err"] = e

    t = threading.Thread(target=_worker, daemon=True, name=f"qlbt-{run_id}")
    t.start()

    st.session_state[f"{state_key}_run_id"] = run_id
    st.session_state[f"{state_key}_is_running"] = True
    st.session_state[f"{state_key}_holder"] = holder
    st.session_state[f"{state_key}_thread"] = t
    st.session_state[f"{state_key}_out_dir"] = str(out_dir)
    st.session_state[f"{state_key}_start_time"] = time.time()
    # Seed the equity series with the starting capital so the live chart has
    # a visible baseline from t=0 — the first streamed point will then update
    # it within ~1 bar. Without this seed the user sees a blank chart for a
    # second or two and reads "no equity visible".
    first_date = pd.Timestamp(panel.index[0]) if not panel.empty else None
    if first_date is not None:
        st.session_state[f"{state_key}_equity_points"] = [
            (first_date.isoformat(), float(initial_capital_eur))
        ]
        st.session_state[f"{state_key}_benchmark_points"] = [
            (first_date.isoformat(), float(initial_capital_eur))
        ]
    else:
        st.session_state[f"{state_key}_equity_points"] = []
        st.session_state[f"{state_key}_benchmark_points"] = []
    st.session_state[f"{state_key}_trade_log"] = []
    st.session_state[f"{state_key}_initial_capital"] = float(initial_capital_eur)
    st.session_state[f"{state_key}_stop_warned"] = False
    return run_id


def _reader_for(state_key: str) -> Optional[StreamReader]:
    rid = st.session_state.get(f"{state_key}_run_id")
    od = st.session_state.get(f"{state_key}_out_dir")
    if rid is None or od is None:
        return None
    return StreamReader(rid, Path(od))


def render_live(*, state_key: str, autorefresh_ms: int = 500) -> Optional[BacktestResult]:
    """Render the live progress UI for a running or just-completed run.

    Returns the final BacktestResult once the run is finished, otherwise None.
    Safe to call on every script rerun.
    """
    if not st.session_state.get(f"{state_key}_run_id"):
        return None

    reader = _reader_for(state_key)
    if reader is None:
        return None

    # Drain new events into session_state buffers
    bench_buf_key = f"{state_key}_benchmark_points"
    st.session_state.setdefault(bench_buf_key, [])
    for ev in reader.read_new_events():
        if ev.event_type == "equity_update":
            st.session_state[f"{state_key}_equity_points"].append(
                (ev.sim_date, ev.data.get("equity_eur"))
            )
            bench_eq = ev.data.get("benchmark_equity_eur")
            if bench_eq is not None:
                st.session_state[bench_buf_key].append((ev.sim_date, float(bench_eq)))
        elif ev.event_type in ("trade_open", "trade_close"):
            st.session_state[f"{state_key}_trade_log"].append(
                {
                    "sim_date": ev.sim_date,
                    "type": ev.event_type,
                    **{k: v for k, v in ev.data.items() if k != "metadata"},
                }
            )

    status = reader.get_status()
    status_label = status.get("status", "unknown")
    is_running = status_label in ("starting", "running")
    initial_capital = float(st.session_state.get(f"{state_key}_initial_capital", 0.0))

    # Header / status banner
    elapsed = time.time() - st.session_state.get(f"{state_key}_start_time", time.time())
    eq_pts = st.session_state.get(f"{state_key}_equity_points", [])
    cur_equity = eq_pts[-1][1] if eq_pts else initial_capital
    pnl = (cur_equity or 0) - initial_capital
    n_trades = len(
        [
            x
            for x in st.session_state.get(f"{state_key}_trade_log", [])
            if x["type"] == "trade_close"
        ]
    )

    # Latest benchmark for the live alpha KPI
    bench_pts_for_header = st.session_state.get(bench_buf_key, [])
    cur_bench = bench_pts_for_header[-1][1] if bench_pts_for_header else initial_capital
    live_alpha_pct = None
    if cur_bench and cur_bench > 0 and cur_equity:
        live_alpha_pct = (cur_equity / cur_bench - 1.0) * 100

    icon = {
        "running": "🟢",
        "starting": "🟡",
        "completed": "🔵",
        "stopped_early": "🛑",
        "error": "🔴",
        "unknown": "⚪",
    }.get(status_label, "⚪")
    cols = st.columns([2, 1, 1, 1, 1])
    cols[0].markdown(f"### {icon} **{status_label}** — `{st.session_state[f'{state_key}_run_id']}`")
    cols[1].metric(
        "Strategy €",
        f"€{cur_equity:,.0f}" if cur_equity else "—",
        delta=f"{(pnl / initial_capital * 100):+.2f}%" if initial_capital else None,
    )
    cols[2].metric(
        "SPY €",
        f"€{cur_bench:,.0f}" if cur_bench else "—",
        delta=(
            f"{(cur_bench / initial_capital - 1) * 100:+.2f}%"
            if initial_capital and cur_bench
            else None
        ),
    )
    if live_alpha_pct is not None:
        cols[3].metric(
            "Alpha vs SPY",
            f"{live_alpha_pct:+.2f}%",
            delta=("ahead" if live_alpha_pct > 0 else "behind"),
        )
    else:
        cols[3].metric("Alpha vs SPY", "—")
    cols[4].metric("Trades closed", n_trades)
    st.caption(f"Elapsed: {elapsed:0.1f}s")

    # Stop control (two-step confirm)
    if is_running:
        stop_col1, stop_col2 = st.columns([1, 4])
        with stop_col1:
            if st.button(
                "🛑 Stop", key=f"{state_key}_stop_btn", type="secondary", disabled=not is_running
            ):
                st.session_state[f"{state_key}_stop_warned"] = True
        with stop_col2:
            if st.session_state.get(f"{state_key}_stop_warned"):
                with st.container(border=True):
                    st.warning(
                        "⚠️ **Stopping early creates selection bias.** "
                        "If you stop because you don't like the current curve, you're "
                        "selecting backtests by outcome — that is **not** valid statistical "
                        "practice. Legit reasons: spotted a setup bug, or run is too slow "
                        "and you'll restart with different params. The run will be marked "
                        "`early_stopped=true` in the outputs."
                    )
                    cc1, cc2, _ = st.columns([1, 1, 4])
                    if cc1.button("Confirm Stop", key=f"{state_key}_stop_confirm", type="primary"):
                        reader.request_cancel()
                        st.info("⏳ Cancellation requested — backtest will stop within 1–2 bars.")
                        st.session_state[f"{state_key}_stop_warned"] = False
                    if cc2.button(
                        "Continue running", key=f"{state_key}_stop_cancel", type="secondary"
                    ):
                        st.session_state[f"{state_key}_stop_warned"] = False

    # Live equity + SPY benchmark overlay
    bench_pts = st.session_state.get(bench_buf_key, [])
    if eq_pts:
        xs = [pd.to_datetime(p[0]) for p in eq_pts]
        ys = [p[1] for p in eq_pts]
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=xs, y=ys, mode="lines", name="Strategy", line=dict(width=2.5, color="#1f77b4")
            )
        )
        if bench_pts:
            bxs = [pd.to_datetime(p[0]) for p in bench_pts]
            bys = [p[1] for p in bench_pts]
            fig.add_trace(
                go.Scatter(
                    x=bxs,
                    y=bys,
                    mode="lines",
                    name="SPY buy-and-hold",
                    line=dict(width=1.5, dash="dash", color="#6b7280"),
                )
            )
        if initial_capital:
            fig.add_hline(
                y=initial_capital,
                line_dash="dot",
                line_color="#cbd5e1",
                annotation_text="initial capital",
                annotation_position="bottom right",
            )
        fig.update_layout(
            template="plotly_white",
            height=400,
            title="Live equity curve — Strategy vs SPY",
            xaxis_title="simulation date",
            yaxis_title="EUR",
            legend=dict(orientation="h", y=-0.2),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Cumulative alpha (strategy / benchmark - 1) — only if benchmark exists
        if bench_pts and len(bench_pts) > 1:
            s_series = pd.Series(ys, index=xs).sort_index()
            b_series = pd.Series(bys, index=bxs).sort_index()
            common = s_series.index.intersection(b_series.index)
            if len(common) > 1:
                s_aligned = s_series.loc[common]
                b_aligned = b_series.loc[common]
                cum_alpha = (s_aligned / s_aligned.iloc[0]) / (b_aligned / b_aligned.iloc[0]) - 1
                cum_alpha_pct = cum_alpha * 100
                fig_a = go.Figure()
                fig_a.add_trace(
                    go.Scatter(
                        x=cum_alpha_pct.index,
                        y=cum_alpha_pct.values,
                        mode="lines",
                        name="cumulative alpha %",
                        fill="tozeroy",
                        line=dict(
                            width=1.5, color="#16a34a" if cum_alpha_pct.iloc[-1] >= 0 else "#dc2626"
                        ),
                    )
                )
                fig_a.add_hline(y=0, line_dash="dot", line_color="gray")
                fig_a.update_layout(
                    template="plotly_white",
                    height=220,
                    title="Cumulative alpha vs SPY (%)",
                    yaxis_title="%",
                    xaxis_title="simulation date",
                    margin=dict(l=0, r=0, t=40, b=20),
                )
                st.plotly_chart(fig_a, use_container_width=True)
    else:
        st.info("Waiting for first equity update…")

    # Live trade log (last 20)
    log = st.session_state.get(f"{state_key}_trade_log", [])
    if log:
        with st.expander(f"Live trade log ({len(log)} events)", expanded=False):
            tail = log[-20:]
            tail_df = pd.DataFrame(tail)
            if "instruments" in tail_df.columns:
                tail_df["instruments"] = tail_df["instruments"].apply(
                    lambda x: ",".join(x) if isinstance(x, list) else x
                )
            st.dataframe(tail_df, use_container_width=True, hide_index=True, height=260)

    # Final state handling
    holder = st.session_state.get(f"{state_key}_holder", {})
    if status_label in ("completed", "stopped_early", "error"):
        st.session_state[f"{state_key}_is_running"] = False
        if status_label == "error":
            err = holder.get("err")
            st.error(f"Backtest crashed: {err}")
            return None
        res: BacktestResult | None = holder.get("res")
        if res is not None:
            if res.early_stopped:
                st.warning(
                    f"⚠️ Backtest **stopped early** at "
                    f"{res.completion_pct * 100:.1f}% of the period. "
                    f"`stop_reason={res.stop_reason}`. Final outputs are marked "
                    f"`early_stopped=true`."
                )
            else:
                st.success(f"✅ Backtest complete — {len(res.trades)} trades.")
            return res
        st.info("Worker has not yet returned the result — refreshing…")
        return None

    return None


def clear_run(state_key: str) -> None:
    """Forget the previous run's session_state so the next click starts clean."""
    keys = [k for k in list(st.session_state.keys()) if k.startswith(f"{state_key}_")]
    for k in keys:
        del st.session_state[k]
