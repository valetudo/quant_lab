"""Bonds Screener — porting of the Flask UI from `bonds/app.py` to Streamlit."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from quant_lab.core.data.providers.borsa_italiana_provider import BorsaItalianaProvider
from quant_lab.ui.utils.cache import get_storage

st.set_page_config(page_title="Bonds Screener", page_icon="💰", layout="wide")
st.title("💰 Bonds Screener")
st.caption("Borsa Italiana sovereign + corporate bond screener.")

storage = get_storage()

if not storage.bonds_db_exists():
    st.error(
        f"Bonds DB not found at `{storage.bonds_db_path}`.\n\n"
        "Run `python scripts/migrate_bonds_db.py` to copy from the legacy "
        "`bonds/bonds.db` into the configured location."
    )
    st.stop()

provider = BorsaItalianaProvider(db_path=storage.bonds_db_path)

with st.spinner("Loading bonds..."):
    df = provider.list_bonds_df(enrich=True)

if df.empty:
    st.warning("No bonds in the DB. Run a scrape first.")
    st.stop()

# ---- filters ------------------------------------------------------------

c1, c2, c3, c4 = st.columns(4)
with c1:
    issuer_filter = st.multiselect(
        "Issuer type", sorted(df["issuer_type"].dropna().unique()),
        default=["Government"] if "Government" in df["issuer_type"].values else None,
    )
with c2:
    ccy_filter = st.multiselect(
        "Currency", sorted(df["currency"].dropna().unique()),
        default=["EUR"] if "EUR" in df["currency"].values else None,
    )
with c3:
    min_y = st.number_input("Min net yield (%)", value=0.0, step=0.1)
    max_y = st.number_input("Max net yield (%)", value=15.0, step=0.5)
with c4:
    min_dur = st.number_input("Min years to maturity", value=0.0, step=0.5)
    max_dur = st.number_input("Max years to maturity", value=30.0, step=1.0)

exclude_callable = st.checkbox("Exclude callable", value=True)
exclude_inflation = st.checkbox("Exclude inflation-linked", value=True)

mask = pd.Series(True, index=df.index)
if issuer_filter:
    mask &= df["issuer_type"].isin(issuer_filter)
if ccy_filter:
    mask &= df["currency"].isin(ccy_filter)
mask &= df["net_yield_pa"].between(min_y, max_y, inclusive="both")
mask &= df["years_to_maturity"].between(min_dur, max_dur, inclusive="both")
if exclude_callable and "is_callable" in df.columns:
    mask &= ~df["is_callable"].fillna(False)
if exclude_inflation and "inflation_linked" in df.columns:
    mask &= ~df["inflation_linked"].fillna(False)

view = df[mask].sort_values("net_yield_pa", ascending=False)

st.metric("Filtered bonds", len(view))

# ---- table --------------------------------------------------------------

cols = [
    "isin", "name", "issuer_type", "currency", "coupon", "latest_price",
    "net_yield_pa", "years_to_maturity", "duration_bucket",
    "sovereign_nation", "is_callable", "inflation_linked", "maturity_date",
]
cols = [c for c in cols if c in view.columns]
st.dataframe(
    view[cols],
    use_container_width=True, hide_index=True,
    column_config={
        "net_yield_pa": st.column_config.NumberColumn("Net Yield (%)", format="%.2f"),
        "years_to_maturity": st.column_config.NumberColumn("Years", format="%.1f"),
        "coupon": st.column_config.NumberColumn("Coupon (%)", format="%.2f"),
        "latest_price": st.column_config.NumberColumn("Price", format="%.2f"),
    },
    height=500,
)

# ---- chart --------------------------------------------------------------

st.subheader("Yield curve (filtered)")
if not view.empty:
    chart_df = view.dropna(subset=["years_to_maturity", "net_yield_pa"])
    if not chart_df.empty:
        fig = px.scatter(
            chart_df, x="years_to_maturity", y="net_yield_pa",
            color="sovereign_nation" if "sovereign_nation" in chart_df.columns else "issuer_type",
            hover_data=["name", "isin", "coupon", "latest_price"],
            title="Net yield vs. years to maturity",
        )
        fig.update_layout(template="plotly_white", height=500)
        st.plotly_chart(fig, use_container_width=True)

# ---- refresh control ----------------------------------------------------

st.markdown("---")
st.subheader("Refresh data")
st.caption("Runs the Selenium scraper against borsaitaliana.it. Requires the `scraping` extra.")
if st.button("🔄 Refresh scraping"):
    with st.spinner("Scraping (may take several minutes)..."):
        result = provider.refresh(headless=True)
    if result.get("status") == "ok":
        st.success(f"Scrape complete: {result}")
        st.cache_data.clear()
    else:
        st.error(f"Scrape failed: {result.get('message', result)}")
