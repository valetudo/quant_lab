"""Backtest Runner — pick a strategy, set parameters, run the engine.

Supports two modes:
  - Live (default): streaming equity curve + Stop button (with selection-bias
    disclaimer). Uses streamlit_autorefresh to poll the event stream.
  - Batch: synchronous run, no UI live, no Stop — for "official" runs that
    must not be interrupted (walk-forward, production backtest history).
"""

from __future__ import annotations

# --- bootstrap: add repo root to sys.path (no pip install needed) ---
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# --- end bootstrap ---

from datetime import date

import numpy as np
import pandas as pd
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh

    _HAS_AUTOREFRESH = True
except ImportError:
    _HAS_AUTOREFRESH = False

from core.analytics.metrics import compute_metrics
from core.backtest.engine import PortfolioBacktester
from core.io.standard_schema import write_standard_outputs
from ui.components.equity_chart import equity_chart
from ui.components.metrics_table import metrics_table
from ui.utils.cache import get_storage
from ui.utils.streaming_runner import (
    clear_run,
    render_live,
    start_live_run,
)

from ui.components.mode_badge import mode_badge

st.set_page_config(page_title="Backtest Lab", page_icon="🔬", layout="wide")
st.title("🔬 Backtest Lab")
mode_badge(
    "hidden",
    "Pagina hidden in v3.0.0: aperta dall'interno di **🎯 Alternative → strategia "
    "→ tab Backtest Lab**. Power-user; non in nav primaria.",
)

st.warning(
    "⚠️ **Backtest Lab è per strategie alternative attive.** Non usarlo per "
    "validare scelte passive (ETF World, bond ladder) — quelle sono decisioni "
    "strutturali, non statistiche. Per asset passivi vedi le pagine dedicate "
    "(💰 Bond Ladder e 🌍 Equity)."
)

storage = get_storage()
repo_root = _PROJECT_ROOT
STATE_KEY = "br"  # session_state prefix for this page

# ---- form ---------------------------------------------------------------

# Strategy choices are auto-discovered via the registry. Adding a new strategy
# (drop a folder under strategies/<id>/) makes it appear here without UI edits.
from core.strategy.registry import StrategyRegistry

_registry = StrategyRegistry()
STRATEGY_CHOICES = sorted(s.id for s in _registry.all() if s.status == "active")
# Keep dummy_buy_and_hold available even though it's in the _examples folder
# (skipped by the registry). It's the reference fixture and needs to stay
# selectable from the UI.
if "dummy_buy_and_hold" not in STRATEGY_CHOICES:
    STRATEGY_CHOICES = ["dummy_buy_and_hold"] + STRATEGY_CHOICES

c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    strat_id = st.selectbox("Strategy", STRATEGY_CHOICES, index=0)
with c2:
    start = st.date_input("Start", value=date(2023, 1, 2))
with c3:
    end = st.date_input("End", value=date(2024, 12, 31))

c4, c5, c6 = st.columns(3)
with c4:
    capital = st.number_input("Capital (EUR)", value=50_000.0, min_value=1000.0, step=1000.0)
with c5:
    commission_bps = st.number_input("Commission (bps)", value=5.0, min_value=0.0, step=1.0)
with c6:
    slippage_bps = st.number_input("Slippage (bps)", value=5.0, min_value=0.0, step=1.0)

tickers_input = st.text_input(
    "Tickers (CSV, only used by dummy_buy_and_hold)",
    value="AAPL,MSFT,SPY",
)

mc1, mc2 = st.columns([1, 3])
with mc1:
    run_mode = st.selectbox(
        "Run mode",
        ["Live (interactive)", "Batch (no interruption)"],
        index=0,
        help=(
            "Live shows a streaming equity curve and lets you Stop. "
            "Batch runs synchronously and cannot be interrupted — use it "
            "for walk-forward or production runs."
        ),
    )
with mc2:
    if run_mode.startswith("Live") and not _HAS_AUTOREFRESH:
        st.caption(
            "⚠️ `streamlit_autorefresh` not installed — Live mode will need a manual refresh."
        )

is_running = bool(st.session_state.get(f"{STATE_KEY}_is_running"))
run_btn = st.button("▶︎ Run backtest", type="primary", disabled=is_running)

# ---- panel/strategy builders ----


def _build_panel(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    panel = storage.load_panel(tickers, start, end)
    if panel.empty:
        idx = pd.bdate_range(start, end)
        if len(idx) == 0:
            return pd.DataFrame()
        rng = np.random.default_rng(42)
        rets = rng.normal(0.0005, 0.01, size=(len(idx), max(len(tickers), 1)))
        prices = 100 * np.cumprod(1 + rets, axis=0)
        cols = tickers if tickers else ["SIM"]
        panel = pd.DataFrame(prices, index=idx, columns=cols)
        st.warning(f"DuckDB had no data for {tickers} in window — using synthetic fallback.")
    return panel


def _make_strategy(strat_id: str, tickers: list[str], capital: float):
    if strat_id == "dummy_buy_and_hold":
        from strategies._examples import DummyBuyAndHold

        return DummyBuyAndHold(tickers=tickers, initial_capital_eur=capital)
    if strat_id == "bonds_income":
        from core.data.providers.borsa_italiana_provider import BorsaItalianaProvider
        from strategies.bonds_income import BondsIncome

        provider = (
            BorsaItalianaProvider(db_path=storage.bonds_db_path)
            if storage.bonds_db_exists()
            else None
        )
        return BondsIncome(bonds_provider=provider, initial_capital_eur=capital)
    if strat_id == "passive_equity":
        from strategies.passive_equity import PassiveEquity

        # v1.1.0: equity sleeve uses VWCE (global FTSE All-World).
        # Pre-v1.1.0 was CSPX (S&P 500). See
        # _migration_log/EQUITY_SLEEVE_GLOBAL_DECISION.md and
        # _migration_log/V5_VS_SPY_DECISION.md.
        return PassiveEquity(symbol="VWCE.MI", initial_capital_eur=capital)
    raise ValueError(strat_id)


def _build_panel_for_strategy(
    strat_id: str, tickers: list[str], start: date, end: date
) -> pd.DataFrame:
    if strat_id == "bonds_income":
        provider = None
        if storage.bonds_db_exists():
            from core.data.providers.borsa_italiana_provider import BorsaItalianaProvider

            provider = BorsaItalianaProvider(db_path=storage.bonds_db_path)
        isins = [b["isin"] for b in (provider.list_bonds() if provider else [])][:30]
        idx = pd.bdate_range(start, end)
        if not isins or len(idx) == 0:
            return pd.DataFrame()
        return pd.DataFrame(100.0, index=idx, columns=isins)
    if strat_id == "passive_equity":
        # Try VWCE first, fall back to VT (US-listed FTSE All-World proxy).
        # CSPX/SPY also included for backward compatibility with pre-v1.1.0 backtests.
        return _build_panel(["VWCE.MI", "VT", "CSPX.L", "SPY"], start, end)
    return _build_panel(tickers, start, end)


def _persist_outputs(res, strat_id, start, end, capital, panel) -> dict:
    eq = res.equity["equity"] if not res.equity.empty else pd.Series(dtype=float)
    metrics = compute_metrics(
        eq, res.trades, capital, open_count=res.open_count, exposure=res.exposure
    )
    out_dir = repo_root / "outputs" / strat_id / f"{start}_{end}"
    paths = write_standard_outputs(
        out_dir,
        strategy_id=strat_id,
        universe=",".join(panel.columns[:5]) + ("..." if len(panel.columns) > 5 else ""),
        currency="EUR",
        trades=res.trades,
        equity=res.equity,
        open_count=res.open_count,
        metrics=metrics,
        period_start=start,
        period_end=end,
        early_stopped=res.early_stopped,
        stop_reason=res.stop_reason,
        completion_pct=res.completion_pct,
    )
    return {"eq": eq, "metrics": metrics, "paths": paths, "out_dir": out_dir}


# ---- handle a new run -----

if run_btn:
    clear_run(STATE_KEY)  # forget any prior run for this page
    tickers = [t.strip() for t in tickers_input.split(",") if t.strip()]
    with st.spinner("Building panel..."):
        panel = _build_panel_for_strategy(strat_id, tickers, start, end)
    if panel.empty:
        st.error("Empty panel — nothing to backtest.")
        st.stop()

    strat = _make_strategy(strat_id, tickers, capital)

    if run_mode.startswith("Batch"):
        with st.spinner("Running backtest (batch, no live updates)..."):
            bt = PortfolioBacktester(
                strat,
                panel,
                initial_capital_eur=capital,
                commission_bps=commission_bps,
                slippage_bps=slippage_bps,
            )
            res = bt.run()
        artifacts = _persist_outputs(res, strat_id, start, end, capital, panel)
        st.success(f"Batch backtest complete — {len(res.trades)} trades.")

        # Overlay vs SPY
        try:
            import plotly.graph_objects as go

            from core.backtest.benchmark import (
                Benchmark,
                alpha_summary,
                classify_outperformance,
            )

            bench_res = Benchmark("SPY").run(start, end, initial_capital_eur=capital)
            summary = alpha_summary(artifacts["eq"], bench_res.daily_equity)
            verdict = classify_outperformance(summary)
            colour = {
                "significant": "#16a34a",
                "marginal": "#f59e0b",
                "underperform": "#dc2626",
                "insufficient_data": "#6b7280",
            }.get(verdict)
            label = {
                "significant": "✅ Significantly outperforms SPY",
                "marginal": "⚠️ Marginal outperformance",
                "underperform": "❌ Underperforms SPY buy-and-hold",
                "insufficient_data": "🟦 Insufficient data",
            }.get(verdict)
            alpha_pp = (summary.get("annualized_alpha") or 0) * 100
            st.markdown(
                f"<div style='padding:14px 18px;border-radius:8px;background:{colour};"
                f"color:white;font-size:1.1em;font-weight:600;'>"
                f"{label} &nbsp;|&nbsp; Alpha: <span style='font-size:1.4em;'>"
                f"{alpha_pp:+.2f} pp/yr</span> &nbsp;|&nbsp; Sharpe Δ "
                f"{summary.get('sharpe_delta', 0):+.2f}</div>",
                unsafe_allow_html=True,
            )
            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=artifacts["eq"].index,
                    y=artifacts["eq"].values,
                    mode="lines",
                    name=strat_id,
                    line=dict(width=2.5, color="#1f77b4"),
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=bench_res.daily_equity.index,
                    y=bench_res.daily_equity.values,
                    mode="lines",
                    name="SPY buy-and-hold",
                    line=dict(width=1.5, dash="dash", color="#6b7280"),
                )
            )
            fig.update_layout(
                template="plotly_white",
                height=420,
                title=f"{strat_id}: equity vs SPY",
                yaxis_title="EUR",
                legend=dict(orientation="h", y=-0.2),
            )
            st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.warning(f"SPY benchmark unavailable: {e}")
            st.plotly_chart(
                equity_chart(artifacts["eq"], title=f"{strat_id}: equity"), use_container_width=True
            )

        cc1, cc2 = st.columns(2)
        with cc1:
            st.subheader("Metrics")
            metrics_table(artifacts["metrics"])
        with cc2:
            st.subheader("Outputs")
            for k, p in artifacts["paths"].items():
                st.markdown(f"- `{k}` → `{p}`")
    else:
        # Live mode — launch worker in a thread and let the rerun loop poll.
        st.session_state[f"{STATE_KEY}_panel_cols"] = list(panel.columns)
        st.session_state[f"{STATE_KEY}_strat_id"] = strat_id
        st.session_state[f"{STATE_KEY}_start"] = start.isoformat()
        st.session_state[f"{STATE_KEY}_end"] = end.isoformat()
        st.session_state[f"{STATE_KEY}_capital"] = capital
        st.session_state[f"{STATE_KEY}_panel_obj"] = panel
        start_live_run(
            state_key=STATE_KEY,
            repo_root=repo_root,
            strategy=strat,
            panel=panel,
            initial_capital_eur=capital,
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
        )

# ---- live mode rendering -----

if st.session_state.get(f"{STATE_KEY}_run_id"):
    if _HAS_AUTOREFRESH and st.session_state.get(f"{STATE_KEY}_is_running"):
        st_autorefresh(interval=500, key=f"{STATE_KEY}_poll")

    res = render_live(state_key=STATE_KEY)

    if res is not None:
        # Persist final outputs once.
        already_saved = st.session_state.get(f"{STATE_KEY}_outputs_saved")
        if not already_saved:
            strat_id_saved = st.session_state.get(f"{STATE_KEY}_strat_id", "unknown")
            start_saved = date.fromisoformat(st.session_state.get(f"{STATE_KEY}_start"))
            end_saved = date.fromisoformat(st.session_state.get(f"{STATE_KEY}_end"))
            capital_saved = float(st.session_state.get(f"{STATE_KEY}_capital", 50_000.0))
            panel_saved = st.session_state.get(f"{STATE_KEY}_panel_obj")
            if panel_saved is not None:
                artifacts = _persist_outputs(
                    res, strat_id_saved, start_saved, end_saved, capital_saved, panel_saved
                )
                st.session_state[f"{STATE_KEY}_outputs_saved"] = artifacts

        artifacts = st.session_state.get(f"{STATE_KEY}_outputs_saved")
        if artifacts:
            st.markdown("---")
            st.subheader("Final results — Strategy vs SPY")

            # SPY benchmark over the same window
            import plotly.graph_objects as go

            from core.backtest.benchmark import (
                Benchmark,
                alpha_summary,
                classify_outperformance,
            )

            start_d = date.fromisoformat(st.session_state[f"{STATE_KEY}_start"])
            end_d = date.fromisoformat(st.session_state[f"{STATE_KEY}_end"])
            cap = float(st.session_state.get(f"{STATE_KEY}_capital", 50_000.0))
            try:
                bench_res = Benchmark("SPY").run(start_d, end_d, initial_capital_eur=cap)
            except Exception as e:
                bench_res = None
                st.warning(f"SPY benchmark unavailable: {e}")

            eq_series = artifacts["eq"]
            metrics = artifacts["metrics"]
            sid = st.session_state.get(f"{STATE_KEY}_strat_id", "strategy")

            if bench_res is not None and not eq_series.empty:
                summary = alpha_summary(eq_series, bench_res.daily_equity)
                verdict = classify_outperformance(summary)
                verdict_colour = {
                    "significant": "#16a34a",
                    "marginal": "#f59e0b",
                    "underperform": "#dc2626",
                    "insufficient_data": "#6b7280",
                }.get(verdict, "#6b7280")
                verdict_label = {
                    "significant": "✅ Significantly outperforms SPY",
                    "marginal": "⚠️ Marginal outperformance",
                    "underperform": "❌ Underperforms SPY buy-and-hold",
                    "insufficient_data": "🟦 Insufficient data",
                }.get(verdict, "?")
                alpha_pp = (summary.get("annualized_alpha") or 0) * 100
                st.markdown(
                    f"<div style='padding:14px 18px;border-radius:8px;background:{verdict_colour};"
                    f"color:white;font-size:1.15em;font-weight:600;'>"
                    f"{verdict_label}  &nbsp;|&nbsp;  Annualised alpha: "
                    f"<span style='font-size:1.5em;'>{alpha_pp:+.2f} pp/yr</span>"
                    f"  &nbsp;|&nbsp;  Sharpe Δ: {summary.get('sharpe_delta', 0):+.2f}"
                    f"  &nbsp;|&nbsp;  Calendar-year wins: "
                    f"{summary.get('calendar_year_wins', 0)}/{summary.get('calendar_year_total', 0)}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                # Overlay chart
                fig = go.Figure()
                fig.add_trace(
                    go.Scatter(
                        x=eq_series.index,
                        y=eq_series.values,
                        mode="lines",
                        name=sid,
                        line=dict(width=2.5, color="#1f77b4"),
                    )
                )
                fig.add_trace(
                    go.Scatter(
                        x=bench_res.daily_equity.index,
                        y=bench_res.daily_equity.values,
                        mode="lines",
                        name="SPY buy-and-hold",
                        line=dict(width=1.5, dash="dash", color="#6b7280"),
                    )
                )
                fig.add_hline(
                    y=cap,
                    line_dash="dot",
                    line_color="#cbd5e1",
                    annotation_text="initial",
                    annotation_position="bottom right",
                )
                fig.update_layout(
                    template="plotly_white",
                    height=420,
                    title=f"{sid}: equity vs SPY",
                    yaxis_title="EUR",
                    legend=dict(orientation="h", y=-0.2),
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.plotly_chart(
                    equity_chart(eq_series, title=f"{sid}: equity"), use_container_width=True
                )

            # Side-by-side metrics
            cc1, cc2, cc3 = st.columns(3)
            cc1.markdown("**Strategy**")
            cc1.metric("Final equity", f"€{metrics.get('final_equity', 0):,.0f}")
            cc1.metric("Total return", f"{(metrics.get('total_return_pct') or 0):+.2f}%")
            cc1.metric("Sharpe", f"{metrics.get('sharpe', 0):.3f}")
            cc1.metric("Max DD", f"{(metrics.get('max_drawdown') or 0) * 100:.2f}%")
            if bench_res is not None:
                cc2.markdown("**SPY buy-and-hold**")
                cc2.metric("Final equity", f"€{bench_res.final_equity_eur:,.0f}")
                cc2.metric("Total return", f"{bench_res.total_return_pct:+.2f}%")
                cc2.metric("Sharpe", f"{bench_res.sharpe:.3f}")
                cc2.metric("Max DD", f"{bench_res.max_drawdown * 100:.2f}%")
                cc3.markdown("**Delta**")
                cc3.metric(
                    "Final equity Δ",
                    f"€{metrics.get('final_equity', 0) - bench_res.final_equity_eur:+,.0f}",
                )
                ret_d = (metrics.get("total_return_pct") or 0) - bench_res.total_return_pct
                cc3.metric("Total return Δ", f"{ret_d:+.2f} pp")
                cc3.metric("Sharpe Δ", f"{(metrics.get('sharpe') or 0) - bench_res.sharpe:+.3f}")
                cc3.metric(
                    "Max DD Δ",
                    f"{((metrics.get('max_drawdown') or 0) - bench_res.max_drawdown) * 100:+.2f} pp",
                    delta=(
                        "better"
                        if (metrics.get("max_drawdown") or 0) > bench_res.max_drawdown
                        else "worse"
                    ),
                )

            # Calendar year table
            if bench_res is not None and not eq_series.empty:
                summary = alpha_summary(eq_series, bench_res.daily_equity)
                cy_table = pd.DataFrame(summary.get("calendar_year_table", []))
                if not cy_table.empty:
                    st.markdown(
                        "**Calendar-year returns** — annual return % vs SPY, alpha column highlights V5 wins"
                    )
                    cy_show = cy_table[
                        ["year", "return_pct_strategy", "return_pct_benchmark", "alpha_pct", "win"]
                    ].copy()
                    cy_show["year"] = cy_show["year"].astype(int)
                    st.dataframe(
                        cy_show,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "return_pct_strategy": st.column_config.NumberColumn(
                                "Strategy %", format="%+.2f"
                            ),
                            "return_pct_benchmark": st.column_config.NumberColumn(
                                "SPY %", format="%+.2f"
                            ),
                            "alpha_pct": st.column_config.NumberColumn("Alpha %", format="%+.2f"),
                            "win": st.column_config.CheckboxColumn("V5 won?"),
                        },
                    )

            with st.expander("Detailed strategy metrics + output paths"):
                cc1, cc2 = st.columns(2)
                with cc1:
                    st.subheader("Metrics")
                    metrics_table(metrics)
                with cc2:
                    st.subheader("Outputs")
                    for k, p in artifacts["paths"].items():
                        st.markdown(f"- `{k}` → `{p}`")
                    if res.early_stopped:
                        st.markdown(
                            "<span style='display:inline-block;padding:4px 10px;"
                            "border-radius:12px;background:#fbcfe8;color:#831843;"
                            "font-weight:600;'>⚠️ Stopped Early</span>",
                            unsafe_allow_html=True,
                        )
