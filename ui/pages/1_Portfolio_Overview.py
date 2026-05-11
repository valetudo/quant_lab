"""Portfolio Overview — Phase 4 (50/30/20).

Reads sleeve targets from ``configs/portfolio.yaml`` and pulls live sleeve
values from ``portfolio.state.PortfolioState``. Equity sleeve is now passive
(VWCE global, via passive_equity strategy); opportunistic sleeve is plug-and-play
(strategies auto-discovered via ``core.strategy.registry``).
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# --- bootstrap: add repo root to sys.path (no pip install needed) ---
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# --- end bootstrap ---

from portfolio.state import PortfolioState

st.set_page_config(page_title="Portfolio Overview", page_icon="🧭", layout="wide")
st.title("🧭 Portfolio Overview")
st.caption(
    "Static strategic allocation: 50/30/20 bonds/equity/opportunistic. "
    "Manual rebalancing — drift > 5pp raises an alert."
)


@st.cache_data(ttl=30)
def _load_state() -> dict:
    """Cache the state for 30 s so polling the page doesn't re-read everything."""
    ps = PortfolioState()
    return {
        "sleeves": list(ps.portfolio.sleeves.keys()),
        "targets": dict(ps.portfolio.allocation.sleeve_targets),
        "threshold_pp": ps.portfolio.allocation.drift_threshold_pp,
        "total_capital": ps.portfolio.total_capital_eur,
        "values": ps.get_current_sleeve_values(),
        "drift": ps.get_drift_analysis(),
        "suggestions": ps.get_rebalance_suggestions(),
        "sleeve_notes": {sid: defn.notes for sid, defn in ps.portfolio.sleeves.items()},
        "strategy_ids_per_sleeve": {
            sid: defn.strategy_ids for sid, defn in ps.portfolio.sleeves.items()
        },
        "opportunistic_strategies": ps.get_opportunistic_strategies(),
        "log": ps.read_rebalance_log(limit=10),
        "archived_strategies": ps.cfg.get("archived_strategies", []),
    }


try:
    state = _load_state()
except Exception as e:
    st.error(f"Could not load portfolio state: {e}\n\nCheck `configs/portfolio.yaml`.")
    st.stop()


# =================================================================
# TOP SUMMARY BANNER
# =================================================================

total_value = sum(state["values"].values())
target_value = state["total_capital"]
total_ret_pct = (total_value / target_value - 1) * 100 if target_value > 0 else 0.0
alerting = [sid for sid, d in state["drift"].items() if d["alert"]]

summary_bg = "#16a34a" if not alerting else "#f59e0b"
alert_line = (
    f"✅ All sleeves within ±{state['threshold_pp']:.0f}pp tolerance."
    if not alerting
    else (
        f"⚠️ {len(alerting)} sleeve(s) drifted &gt; {state['threshold_pp']:.0f}pp → "
        f"<b>{', '.join(alerting)}</b>. See Rebalance Suggestions below."
    )
)
st.markdown(
    f"<div style='padding:18px 22px;border-radius:10px;background:{summary_bg};"
    f"color:white;margin:8px 0 18px 0;font-size:1.05em;'>"
    f"<div style='font-size:1.1em;font-weight:700;margin-bottom:6px;'>"
    f"PORTFOLIO SUMMARY ({datetime.now():%Y-%m-%d %H:%M})</div>"
    f"<div style='margin-bottom:8px;'>"
    f"Total value: <b>€{total_value:,.0f}</b> "
    f"(target €{target_value:,.0f}, return {total_ret_pct:+.2f}%)</div>"
    f"<div style='margin-bottom:8px;'>"
    f"Bonds (50%): <b>€{state['values']['bonds']:,.0f}</b>  "
    f"•  Equity (30%): <b>€{state['values']['equity']:,.0f}</b>  "
    f"•  Opportunistic (20%): <b>€{state['values']['opportunistic']:,.0f}</b></div>"
    f"<div>{alert_line}</div>"
    f"</div>",
    unsafe_allow_html=True,
)


# =================================================================
# SECTION 1 — Allocation status (pie + drift table)
# =================================================================

SLEEVE_COLOURS = {"bonds": "#1f77b4", "equity": "#16a34a", "opportunistic": "#f59e0b"}

col_pie, col_tab = st.columns([1, 1])

with col_pie:
    df_pie = pd.DataFrame(
        [
            {
                "sleeve": sid,
                "current_pct": state["drift"][sid]["current_pct"],
                "current_value_eur": state["drift"][sid]["current_value_eur"],
                "target_pct": state["drift"][sid]["target_pct"],
            }
            for sid in state["sleeves"]
        ]
    )
    fig = px.pie(
        df_pie,
        values="current_value_eur",
        names="sleeve",
        hole=0.45,
        color="sleeve",
        color_discrete_map=SLEEVE_COLOURS,
    )
    fig.update_traces(
        textposition="inside",
        texttemplate="%{label}<br>%{percent}<br>(target %{customdata[0]:.1f}%)",
        customdata=df_pie[["target_pct"]].values,
        hovertemplate="<b>%{label}</b><br>Current: %{percent}<br>"
        "Target: %{customdata[0]:.1f}%<br>Value: €%{value:,.0f}<extra></extra>",
    )
    fig.update_layout(
        template="plotly_white",
        height=340,
        margin=dict(l=0, r=0, t=24, b=0),
        title="Current allocation (50/30/20 target)",
    )
    st.plotly_chart(fig, use_container_width=True)

with col_tab:
    rows = []
    for sid in state["sleeves"]:
        d = state["drift"][sid]
        rows.append(
            {
                "Sleeve": sid,
                "Target %": d["target_pct"],
                "Current %": d["current_pct"],
                "Drift pp": d["drift_pp"],
                "Status": "⚠️ drift" if d["alert"] else "✅ on target",
                "Current €": d["current_value_eur"],
                "Target €": d["target_value_eur"],
            }
        )
    df_tab = pd.DataFrame(rows).sort_values("Drift pp", key=lambda s: s.abs(), ascending=False)
    st.dataframe(
        df_tab,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Target %": st.column_config.NumberColumn(format="%.1f%%"),
            "Current %": st.column_config.NumberColumn(format="%.1f%%"),
            "Drift pp": st.column_config.NumberColumn(format="%+.1f"),
            "Current €": st.column_config.NumberColumn(format="€%.0f"),
            "Target €": st.column_config.NumberColumn(format="€%.0f"),
        },
    )


# =================================================================
# SECTION 2 — Rebalance suggestions
# =================================================================

with st.expander("💡 Rebalance Suggestions", expanded=bool(alerting)):
    if not state["suggestions"]:
        st.info("No rebalance suggested — all sleeves within tolerance.")
    else:
        st.markdown(
            "Below are concrete moves that would restore the target allocation. "
            "The page does **not** execute them — perform the transfers at your "
            "broker, then click *Mark as rebalanced* to record the event."
        )
        for i, s in enumerate(state["suggestions"]):
            with st.container(border=True):
                cs1, cs2 = st.columns([3, 1])
                with cs1:
                    st.markdown(
                        f"**Move €{s['amount_eur']:,.0f}** from **{s['from_sleeve']}** "
                        f"→ **{s['to_sleeve']}**"
                    )
                    st.caption(s["reason"])
                with cs2:
                    if st.button("Mark as rebalanced", key=f"reb_{i}", type="primary"):
                        ps = PortfolioState()
                        ps.log_rebalance_event(
                            description=f"Manual rebalance: €{s['amount_eur']:,.0f} "
                            f"{s['from_sleeve']} → {s['to_sleeve']}",
                            payload=s,
                        )
                        st.cache_data.clear()
                        st.success("Recorded.")
                        st.rerun()


# =================================================================
# SECTION 3 — Per-sleeve dashboard
# =================================================================

st.markdown("---")
st.subheader("Per-sleeve detail")
tab_bonds, tab_equity, tab_opp = st.tabs(
    ["💰 Bonds (50%)", "📈 Equity (30%)", "🎲 Opportunistic (20%)"]
)


# ---- BONDS TAB (unchanged from Phase 3) -------------------------

with tab_bonds:
    d = state["drift"]["bonds"]
    bc1, bc2, bc3, bc4 = st.columns(4)
    bc1.metric("Sleeve value", f"€{d['current_value_eur']:,.0f}")
    bc2.metric("vs target", f"{d['drift_pp']:+.1f}pp", delta=f"€{d['delta_eur']:+,.0f}")
    bc3.metric("Strategies", ", ".join(state["strategy_ids_per_sleeve"]["bonds"]) or "—")

    positions_path = _PROJECT_ROOT / "data_storage" / "bonds" / "positions.parquet"
    if positions_path.exists():
        try:
            pos_df = pd.read_parquet(positions_path)
            if "status" in pos_df.columns:
                pos_df = pos_df[pos_df["status"] == "active"]
        except Exception as e:
            st.warning(f"could not read bond positions: {e}")
            pos_df = pd.DataFrame()
    else:
        pos_df = pd.DataFrame()

    bc4.metric("Positions", len(pos_df))

    if pos_df.empty:
        st.info(
            "No bond positions on file yet. Open the **Bond Ladder** page "
            "(left sidebar) to design and track your ladder."
        )
    else:
        ytm_col = "ytm_current" if "ytm_current" in pos_df.columns else "ytm_at_purchase"
        val_col = (
            "current_market_value_eur" if "current_market_value_eur" in pos_df.columns else None
        )
        weights = (
            (pos_df[val_col] / pos_df[val_col].sum())
            if val_col
            else pd.Series(1.0 / len(pos_df), index=pos_df.index)
        )
        wavg_ytm = float((pos_df.get(ytm_col, pd.Series(dtype=float)).fillna(0) * weights).sum())
        wavg_dur = float(
            (pos_df.get("years_to_maturity", pd.Series(dtype=float)).fillna(0) * weights).sum()
        )
        sc1, sc2 = st.columns(2)
        sc1.metric("Weighted avg YTM", f"{wavg_ytm:.2f}%")
        sc2.metric("Weighted avg duration", f"{wavg_dur:.1f}y")

        show_cols = [
            c
            for c in [
                "isin",
                "description",
                "quantity",
                "avg_purchase_price",
                "current_price",
                "current_market_value_eur",
                ytm_col,
                "years_to_maturity",
                "maturity_date",
                "nation",
                "issuer_type",
            ]
            if c in pos_df.columns
        ]
        st.dataframe(pos_df[show_cols], use_container_width=True, hide_index=True, height=300)

    st.caption("→ Manage positions on the Bond Ladder page.")


# ---- EQUITY TAB (Phase 4 / v1.1.0 — passive global VWCE) ----------------

with tab_equity:
    d = state["drift"]["equity"]
    ec1, ec2, ec3 = st.columns(3)
    ec1.metric("Sleeve value", f"€{d['current_value_eur']:,.0f}")
    ec2.metric("vs target", f"{d['drift_pp']:+.1f}pp", delta=f"€{d['delta_eur']:+,.0f}")
    ec3.metric("Strategy", ", ".join(state["strategy_ids_per_sleeve"]["equity"]) or "—")

    st.markdown(
        "<div style='background:#dcfce7;border-left:4px solid #16a34a;padding:12px 16px;"
        "border-radius:4px;margin:14px 0;'>"
        "<b>Passive Global Equity via VWCE.MI</b> (Vanguard FTSE All-World UCITS ETF, "
        "~3700 holdings, developed + emerging, TER 0.19%). "
        "<br>v1.1.0 (May 2026): switched from CSPX (S&P 500 USA) to VWCE for global diversification — "
        "see <code>_migration_log/EQUITY_SLEEVE_GLOBAL_DECISION.md</code>. "
        "Equity sleeve was earlier flipped from active V5 to passive after V5 underperformed "
        "SPY by −4.6 %/yr in 13-year OOS — see <code>_migration_log/V5_VS_SPY_DECISION.md</code>."
        "</div>",
        unsafe_allow_html=True,
    )

    # VWCE (or VT proxy) recent equity curve, scaled to the sleeve target
    try:
        from core.data.storage import DataStorage, load_global_config

        storage = DataStorage.from_config(load_global_config())
        df = storage.get_prices_with_proxy("VWCE.MI")
        if df is None or df.empty:
            st.info("Price data for VWCE.MI (and VT proxy) not available.")
        else:
            proxy_label = df.attrs.get("proxy_for")
            px_used = df.attrs.get("proxy_symbol", "VWCE.MI")
            # Last 12 months
            last_12m = df.tail(252)
            if not last_12m.empty:
                base = float(last_12m["adj_close"].iloc[0])
                series = (last_12m["adj_close"] / base) * d["current_value_eur"]

                fig_eq = go.Figure()
                fig_eq.add_trace(
                    go.Scatter(
                        x=series.index,
                        y=series.values,
                        mode="lines",
                        name=("VWCE.MI (via VT proxy)" if proxy_label else "VWCE.MI"),
                        line=dict(width=2, color="#16a34a"),
                    )
                )
                fig_eq.update_layout(
                    template="plotly_white",
                    height=280,
                    title="Equity sleeve — last 12 months",
                    yaxis_title="EUR (scaled to current sleeve value)",
                    margin=dict(l=0, r=0, t=40, b=0),
                )
                st.plotly_chart(fig_eq, use_container_width=True)

                # Distance from ATH
                ath = float(df["adj_close"].max())
                last_px = float(df["adj_close"].iloc[-1])
                dist_ath = (last_px / ath - 1) * 100
                ydays = 252
                yr_ago = (
                    df["adj_close"].iloc[-ydays] if len(df) >= ydays else df["adj_close"].iloc[0]
                )
                ret_12m = (last_px / float(yr_ago) - 1) * 100
                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("Last close", f"{last_px:.2f}")
                mc2.metric("12-month return", f"{ret_12m:+.2f}%")
                mc3.metric("Distance from ATH", f"{dist_ath:+.2f}%")

                if proxy_label:
                    st.caption(
                        f"⚠️ Backtest using `{px_used}` as a proxy for `{proxy_label}` "
                        f"(US-listed equivalent — VT tracks the same FTSE All-World index). "
                        f"The actual broker position is VWCE.MI."
                    )
    except Exception as e:
        st.warning(f"Equity curve unavailable: {e}")

    # Archived strategies link
    archived = state.get("archived_strategies", [])
    qs = next((a for a in archived if a.get("id") == "quality_stocks"), None)
    if qs:
        st.caption(
            f"Previous active strategy `quality_stocks` archived "
            f"{qs.get('archived_date')}. Reason: {qs.get('reason')}. "
            f"Decision report: `{qs.get('decision_report')}`"
        )


# ---- OPPORTUNISTIC TAB (Phase 4 — plug-and-play) -----------------

with tab_opp:
    d = state["drift"]["opportunistic"]
    oc1, oc2, oc3 = st.columns(3)
    oc1.metric("Sleeve value", f"€{d['current_value_eur']:,.0f}")
    oc2.metric("vs target", f"{d['drift_pp']:+.1f}pp")
    oc3.metric("Active strategies", len(state["opportunistic_strategies"]))

    st.info(
        "**20% reserved for short-term opportunistic strategies.** "
        "Plug-and-play: drop a folder under `strategies/<id>/` with a `strategy.py` "
        "and `config.yaml`, and it auto-registers here on the next refresh."
    )

    opp_strats = state["opportunistic_strategies"]
    if not opp_strats:
        st.markdown(
            "<div style='padding:12px 16px;background:#fef3c7;border-radius:6px;"
            "border-left:4px solid #f59e0b;'>"
            "No active strategies in this sleeve. Capital "
            f"(€{state['values']['opportunistic']:,.0f}) sits as cash."
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        for s in opp_strats:
            with st.container(border=True):
                cols = st.columns([3, 1, 1])
                cols[0].markdown(f"**`{s['id']}`** — _{s['status']}_")
                if s.get("description"):
                    cols[0].caption(s["description"])
                cols[1].metric("Status", s["status"])
                cols[2].metric("Sleeve", s["sleeve"])
                if s["status"] == "scaffold":
                    cols[0].markdown(
                        ":warning: Scaffolded — not yet active. See `README.md` "
                        "in the strategy folder for activation steps."
                    )

    st.markdown(
        "**Adding a new strategy** — see "
        "`docs/adding_a_strategy.md`. Restart Streamlit to pick up changes."
    )


# =================================================================
# SECTION 4 — Aggregate metrics (footer)
# =================================================================

st.markdown("---")
st.subheader("Aggregate")

ag1, ag2, ag3 = st.columns(3)
ag1.metric(
    "Total portfolio value",
    f"€{total_value:,.0f}",
    delta=f"€{(total_value - target_value):+,.0f} vs target",
)
ag2.metric("Target capital", f"€{target_value:,.0f}")
ag3.metric("Number of sleeves", len(state["sleeves"]))

with st.expander("🧾 Rebalance audit log", expanded=False):
    log = state["log"]
    if not log:
        st.info("No rebalance events recorded yet.")
    else:
        log_df = pd.DataFrame(log)
        st.dataframe(log_df, use_container_width=True, hide_index=True, height=200)

st.caption(f"Last refreshed: {datetime.now():%Y-%m-%d %H:%M:%S}  •  Cached for 30s.")
