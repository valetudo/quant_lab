"""Bond Ladder — design, track, and gap-fill a manually managed bond ladder.

Reads / writes ``data_storage/bonds/positions.parquet``. Pulls candidates from
the Bonds Screener (the same BorsaItalianaProvider data the Screener page uses).
No live trading — this is decision support only.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# --- bootstrap ---
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# ---

from core.data.providers.borsa_italiana_provider import BorsaItalianaProvider
from strategies.bonds_income.ladder import LadderConfig, LadderTracker
from ui.utils.cache import get_storage

st.set_page_config(page_title="Bond Ladder", page_icon="🏗️", layout="wide")
st.title("🏗️ Bond Ladder Designer")
st.caption("Track your bond ladder. Identify gaps. Suggest candidates. NOT a trading strategy.")

st.info(
    "💡 Vuoi **costruire un nuovo ladder da zero** invece di tracciare uno "
    "esistente? Vai alla pagina **🏗️ Ladder Builder** dal menù laterale: "
    "imposti budget + n° gradini + duration e ottieni una proposta concreta "
    "di acquisto da portare al broker."
)

storage = get_storage()

# Sidebar: ladder config
st.sidebar.header("Target ladder")
n_buckets = st.sidebar.slider("Maturity buckets (years)", 5, 15, value=10)
sovereign_w = st.sidebar.slider("Sovereign weight", 0.0, 1.0, value=0.70, step=0.05)
liq_reserve = st.sidebar.slider("Liquidity reserve %", 0.0, 20.0, value=5.0, step=1.0)
max_issuer = st.sidebar.slider("Max issuer concentration %", 1.0, 25.0, value=5.0, step=0.5)

cfg = LadderConfig(
    maturity_buckets_years=tuple(range(1, n_buckets + 1)),
    sovereign_weight=sovereign_w,
    corporate_weight=round(1.0 - sovereign_w, 4),
    liquidity_reserve_pct=liq_reserve,
    max_issuer_concentration_pct=max_issuer,
)
tracker = LadderTracker(config=cfg)
active = tracker.active


# =================================================================
# SECTION 1 — Ladder composition
# =================================================================

st.subheader("Ladder composition")

if active.empty:
    st.info(
        "No bond positions yet. Use *Section 4 — Add a position* below to "
        "enter your first bond, or use the gap analysis to find candidates."
    )

comp = tracker.get_ladder_composition()
if not comp.empty:
    # Stacked bar chart: x=bucket, y=value, stacked sovereign/corporate
    bar_df = comp.melt(
        id_vars=["maturity_bucket", "target_pct", "current_pct"],
        value_vars=["sovereign_value_eur", "corporate_value_eur"],
        var_name="issuer_type",
        value_name="value_eur",
    )
    bar_df["issuer_type"] = bar_df["issuer_type"].map(
        {
            "sovereign_value_eur": "Government",
            "corporate_value_eur": "Corporate",
        }
    )
    fig = go.Figure()
    for it, colour in [("Government", "#1f77b4"), ("Corporate", "#ff7f0e")]:
        sub = bar_df[bar_df["issuer_type"] == it]
        fig.add_trace(
            go.Bar(
                x=sub["maturity_bucket"],
                y=sub["value_eur"],
                name=it,
                marker_color=colour,
            )
        )
    fig.update_layout(
        barmode="stack",
        template="plotly_white",
        height=340,
        title="Value per maturity bucket",
        yaxis_title="EUR",
        xaxis_title="Maturity bucket",
        margin=dict(l=0, r=0, t=40, b=0),
    )
    # Overlay target line (average per-bucket € if total > 0)
    total_value = float(comp["total_value_eur"].sum())
    if total_value > 0:
        per_bucket_target = total_value / len(comp)
        fig.add_hline(
            y=per_bucket_target,
            line_dash="dot",
            line_color="gray",
            annotation_text=f"target {per_bucket_target:,.0f}€/bucket",
            annotation_position="top right",
        )
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        comp,
        use_container_width=True,
        hide_index=True,
        column_config={
            "total_value_eur": st.column_config.NumberColumn("Value €", format="%.0f"),
            "sovereign_value_eur": st.column_config.NumberColumn("Sovereign €", format="%.0f"),
            "corporate_value_eur": st.column_config.NumberColumn("Corporate €", format="%.0f"),
            "weighted_avg_ytm": st.column_config.NumberColumn("Avg YTM", format="%.2f%%"),
            "current_pct": st.column_config.NumberColumn("Current %", format="%.1f"),
            "target_pct": st.column_config.NumberColumn("Target %", format="%.1f"),
        },
    )


# =================================================================
# SECTION 2 — Cash flow projection
# =================================================================

st.markdown("---")
st.subheader("Cash flow projection (next 24 months)")
st.caption(
    "⚠️ MOCK DATA assumption: annual coupon on maturity anniversary. "
    "Real coupon schedules (frequency, ex-coupon) will land with the Phase 4 data feed."
)

cf = tracker.get_cash_flow_projection(horizon_weeks=104)
if cf.empty:
    st.info("No projected cash flows — add positions to see coupons + maturity events.")
else:
    cf["month"] = pd.to_datetime(cf["date"]).dt.to_period("M").astype(str)
    monthly = cf.groupby(["month", "type"])["amount_eur"].sum().reset_index()
    fig_cf = px.bar(
        monthly,
        x="month",
        y="amount_eur",
        color="type",
        color_discrete_map={"coupon": "#2ca02c", "maturity": "#d62728"},
        title="Projected EUR by month",
    )
    fig_cf.update_layout(
        template="plotly_white",
        height=320,
        yaxis_title="EUR",
        xaxis_title="Month",
        margin=dict(l=0, r=0, t=40, b=0),
    )
    st.plotly_chart(fig_cf, use_container_width=True)

    with st.expander(f"All {len(cf)} cash flow events", expanded=False):
        st.dataframe(cf, use_container_width=True, hide_index=True, height=300)


# =================================================================
# SECTION 3 — Gap analysis & candidate suggestions
# =================================================================

st.markdown("---")
st.subheader("Gap analysis")

gaps = tracker.get_gaps()
if not gaps:
    st.success("✅ No bucket gaps detected.")
else:
    # Load screener data once for candidate ranking
    if storage.bonds_db_exists():
        try:
            provider = BorsaItalianaProvider(db_path=storage.bonds_db_path)
            screener_df = provider.list_bonds_df(enrich=True)
        except Exception as e:
            screener_df = pd.DataFrame()
            st.warning(f"Could not load screener data: {e}")
    else:
        screener_df = pd.DataFrame()
        st.info(
            "Bonds DB not found — candidate suggestions disabled. "
            "Run `python scripts/migrate_bonds_db.py` first."
        )

    for g in gaps[:n_buckets]:  # show all gap buckets up to ladder width
        with st.container(border=True):
            st.markdown(
                f"**{g['bucket']} bucket** — target {g['target_pct']:.1f}%, "
                f"current {g['current_pct']:.1f}% → "
                f"gap **€{g['gap_eur']:,.0f}**"
            )
            if screener_df is not None and not screener_df.empty:
                col_y, col_curr, col_show = st.columns([1, 1, 1])
                with col_y:
                    max_yield = st.number_input(
                        "Max net yield %", value=15.0, key=f"my_{g['bucket']}", step=0.5
                    )
                with col_curr:
                    currency = st.selectbox(
                        "Currency", ["EUR", "USD", "GBP"], index=0, key=f"cur_{g['bucket']}"
                    )
                with col_show:
                    show_btn = st.button("Show candidates", key=f"show_{g['bucket']}")
                if show_btn:
                    filt = screener_df[screener_df["net_yield_pa"].fillna(0) <= max_yield]
                    candidates = tracker.suggest_candidates_for_bucket(
                        g["bucket"],
                        filt,
                        n_suggestions=10,
                        currency=currency,
                    )
                    if candidates.empty:
                        st.warning("No matching candidates.")
                    else:
                        cand_cols = [
                            c
                            for c in [
                                "isin",
                                "name",
                                "issuer_type",
                                "currency",
                                "coupon",
                                "net_yield_pa",
                                "years_to_maturity",
                                "latest_price",
                                "maturity_date",
                            ]
                            if c in candidates.columns
                        ]
                        st.dataframe(
                            candidates[cand_cols],
                            use_container_width=True,
                            hide_index=True,
                            height=240,
                        )
                        st.caption(
                            "Use the *Add a position* form below to "
                            "purchase from this list (manual entry)."
                        )


# =================================================================
# SECTION 4 — Position manager
# =================================================================

st.markdown("---")
st.subheader("Position manager")

with st.expander("➕ Add a position", expanded=active.empty):
    add_col1, add_col2, add_col3 = st.columns(3)
    with add_col1:
        new_isin = st.text_input("ISIN", value="", key="add_isin").strip()
        new_desc = st.text_input("Description", value="", key="add_desc")
        new_qty = st.number_input("Quantity (face value €)", value=10000, step=1000, key="add_qty")
    with add_col2:
        new_pp = st.number_input("Purchase price (% of face)", value=100.0, step=0.1, key="add_pp")
        new_pdate = st.date_input("Purchase date", value=date.today(), key="add_pdate")
        new_ytm = st.number_input("YTM at purchase (%)", value=3.0, step=0.1, key="add_ytm")
    with add_col3:
        new_coupon = st.number_input("Coupon (% per year)", value=3.0, step=0.1, key="add_coupon")
        new_mdate = st.date_input(
            "Maturity date", value=date(date.today().year + 5, 1, 15), key="add_mdate"
        )
        new_itype = st.selectbox(
            "Issuer type", ["Government", "Corporate"], index=0, key="add_itype"
        )
    add_col4, add_col5, add_col6 = st.columns(3)
    with add_col4:
        new_nation = st.text_input("Nation", value="Italia", key="add_nation")
    with add_col5:
        new_rating = st.text_input("Rating (corporate only)", value="", key="add_rating")
    with add_col6:
        new_notes = st.text_input("Notes", value="", key="add_notes")
    if st.button("Add position", type="primary", key="add_btn"):
        if not new_isin:
            st.error("ISIN required.")
        else:
            try:
                tracker.add_position(
                    isin=new_isin,
                    description=new_desc,
                    quantity=int(new_qty),
                    avg_purchase_price=float(new_pp),
                    purchase_date=new_pdate,
                    ytm_at_purchase=float(new_ytm),
                    coupon=float(new_coupon),
                    maturity_date=new_mdate,
                    nation=new_nation or None,
                    issuer_type=new_itype,
                    rating=new_rating or None,
                    notes=new_notes or "",
                )
                st.success(f"Added {new_isin}.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not add: {e}")

if not active.empty:
    edit_cols = [
        "isin",
        "description",
        "quantity",
        "avg_purchase_price",
        "current_price",
        "current_market_value_eur",
        "ytm_current",
        "years_to_maturity",
        "maturity_date",
        "nation",
        "issuer_type",
        "rating",
        "status",
    ]
    edit_cols = [c for c in edit_cols if c in active.columns]
    st.dataframe(active[edit_cols], use_container_width=True, hide_index=True, height=300)

    with st.expander("✏️ Update / close position", expanded=False):
        isins = active["isin"].tolist()
        pick = st.selectbox("Pick ISIN", isins, key="edit_pick")
        row = active[active["isin"] == pick].iloc[0] if pick else None
        if row is not None:
            uc1, uc2, uc3 = st.columns(3)
            with uc1:
                upd_qty = st.number_input(
                    "Quantity", value=int(row["quantity"]), step=1000, key="upd_qty"
                )
            with uc2:
                upd_price = st.number_input(
                    "Current price (% of face)",
                    value=float(row["current_price"] or 100.0),
                    step=0.1,
                    key="upd_price",
                )
            with uc3:
                upd_ytm = st.number_input(
                    "Current YTM (%)",
                    value=float(row["ytm_current"] or row["ytm_at_purchase"] or 0.0),
                    step=0.1,
                    key="upd_ytm",
                )
            ub1, ub2, ub3 = st.columns([1, 1, 2])
            with ub1:
                if st.button("Update", key="upd_btn"):
                    tracker.update_position(
                        pick, quantity=upd_qty, current_price=upd_price, ytm_current=upd_ytm
                    )
                    st.success("Updated.")
                    st.rerun()
            with ub2:
                if st.button("Mark matured", key="mat_btn", type="secondary"):
                    tracker.close_position(pick, reason="matured", closed_price=upd_price)
                    st.success("Marked matured.")
                    st.rerun()
            with ub3:
                if st.button("Mark sold", key="sold_btn", type="secondary"):
                    tracker.close_position(pick, reason="sold", closed_price=upd_price)
                    st.success("Marked sold.")
                    st.rerun()


# =================================================================
# SECTION 5 — Health check
# =================================================================

st.markdown("---")
st.subheader("Ladder health check")
h = tracker.health_check()
hc1, hc2, hc3, hc4 = st.columns(4)
hc1.metric("Health score", f"{h['score']:.0f}/100")
hc2.metric("Sovereign %", f"{h['metrics']['sovereign_pct']:.1f}%")
hc3.metric("Avg YTM", f"{h['metrics']['weighted_avg_ytm']:.2f}%")
hc4.metric("Avg duration", f"{h['metrics']['weighted_avg_duration']:.1f}y")

if h["warnings"]:
    for w in h["warnings"]:
        if w["level"] == "warning":
            st.warning(w["message"])
        else:
            st.info(w["message"])
else:
    st.success("No health warnings.")
