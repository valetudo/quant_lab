"""Bonds — screener su bonds.db + aggiornamento prezzi (v3.1.0).

In cima: stato freshness + bottone aggiornamento (worker thread + progress
bar, ETA, cancel — wired al pannello di v3.0.1).

Sotto: il vecchio Bonds Screener (filtri, tabella, yield-curve scatter)
così com'è.

Sostituisce nella nav v3.1.0 la vecchia ``4_Bonds_Ladder.py`` (archiviata)
e la vecchia ``10_Bonds_Screener.py`` (archiviata).
"""

from __future__ import annotations

import os
import sys
import time as _time
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# --- bootstrap ---
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# ---

from core.data.providers.borsa_italiana_provider import BorsaItalianaProvider
from core.data.refresh_bonds import get_state as _get_refresh_state
from ui.components.bonds_refresh_progress import render_refresh_panel
from ui.components.mode_badge import mode_badge
from ui.utils.cache import get_storage

st.set_page_config(page_title="Bonds", page_icon="💰", layout="wide")
st.title("💰 Bonds")
mode_badge(
    "ricerca",
    "Screener del catalogo bond di Borsa Italiana. Filtri, tabella, yield "
    "curve + aggiornamento prezzi in-process.",
)

storage = get_storage()
bonds_db = storage.bonds_db_path if hasattr(storage, "bonds_db_path") else None

# =========================================================
# FRESHNESS BANNER + REFRESH PANEL (top of page)
# =========================================================

_refresh_status = _get_refresh_state().status

if _refresh_status == "idle":
    # Compact layout: freshness banner left, refresh button right.
    fs1, fs2 = st.columns([3, 1])
    with fs1:
        if bonds_db and bonds_db.exists():
            last_modified = pd.Timestamp.fromtimestamp(os.path.getmtime(bonds_db))
            age_days = (pd.Timestamp.now() - last_modified).days
            if age_days < 2:
                st.success(
                    f"✅ Dati bonds aggiornati "
                    f"({last_modified.strftime('%Y-%m-%d %H:%M')}, "
                    f"{age_days}g fa)"
                )
            elif age_days < 7:
                st.info(
                    f"📅 Ultimo aggiornamento bonds: {age_days} giorni fa "
                    f"({last_modified.strftime('%Y-%m-%d')})"
                )
            else:
                st.warning(
                    f"⚠️ Dati bonds stale: {age_days} giorni fa. "
                    "Aggiorna per prezzi più recenti."
                )
        else:
            st.error("❌ Database bonds non trovato. Aggiorna ora.")
    with fs2:
        _refresh_should_rerun = render_refresh_panel()
else:
    # Full-width: progress bar + metrics + cancel get the space they need.
    _refresh_should_rerun = render_refresh_panel()

# Auto-rerun while the worker thread is scraping.
if _refresh_should_rerun:
    _time.sleep(2)
    st.rerun()

st.markdown("---")


# =========================================================
# SCREENER (migrated from old 10_Bonds_Screener.py)
# =========================================================

if not storage.bonds_db_exists():
    st.error(
        f"Bonds DB non trovato in `{storage.bonds_db_path}`.\n\n"
        "Esegui `python scripts/migrate_bonds_db.py` per copiare dal sister "
        "repo, oppure usa il bottone **🔄 Aggiorna prezzi bonds** qui sopra "
        "per fare uno scrape from scratch."
    )
    st.stop()

provider = BorsaItalianaProvider(db_path=storage.bonds_db_path)

with st.spinner("Caricamento bonds..."):
    df = provider.list_bonds_df(enrich=True)

if df.empty:
    st.warning(
        "Nessun bond in DB. Lancia un refresh dal pannello in alto per "
        "popolarlo."
    )
    st.stop()


# ---- derive country + duration_bucket once for filter speed --------------

DURATION_BUCKETS = ["0-2y", "2-5y", "5-10y", "10y+"]


def _country_from_isin(isin) -> str | None:
    if not isinstance(isin, str) or len(isin) < 2:
        return None
    code = isin[:2].upper()
    mapping = {
        "IT": "Italia",
        "DE": "Germania",
        "FR": "Francia",
        "ES": "Spagna",
        "GB": "Regno Unito",
        "US": "Stati Uniti",
        "AT": "Austria",
        "BE": "Belgio",
        "FI": "Finlandia",
        "GR": "Grecia",
        "IE": "Irlanda",
        "LU": "Lussemburgo",
        "NL": "Olanda",
        "PL": "Polonia",
        "PT": "Portogallo",
        "HU": "Ungheria",
        "CH": "Svizzera",
        "SE": "Svezia",
        "NO": "Norvegia",
        "DK": "Danimarca",
        "JP": "Giappone",
        "CA": "Canada",
        "AU": "Australia",
        "XS": "Eurobond",
    }
    return mapping.get(code)


def _country_from_name(name) -> str | None:
    if not isinstance(name, str):
        return None
    upper = name.upper()
    name_tokens = [
        ("BTP", "Italia"),
        ("ITALIA", "Italia"),
        ("CCTEU", "Italia"),
        ("BUND", "Germania"),
        ("BOBL", "Germania"),
        ("SCHATZ", "Germania"),
        ("OAT", "Francia"),
        ("BONOS", "Spagna"),
        ("GILT", "Regno Unito"),
        ("TREASURY", "Stati Uniti"),
        ("T-NOTE", "Stati Uniti"),
        ("T-BOND", "Stati Uniti"),
    ]
    for token, country in name_tokens:
        if token in upper:
            return country
    return None


def _resolve_country(row) -> str | None:
    for col in ("sovereign_nation", "nation", "geo_area"):
        v = row.get(col)
        if isinstance(v, str) and v.strip():
            return v.strip()
    fc = _country_from_isin(row.get("isin"))
    if fc:
        return fc
    return _country_from_name(row.get("name"))


def _make_duration_bucket(yrs) -> str | None:
    if pd.isna(yrs):
        return None
    y = float(yrs)
    if y < 2:
        return "0-2y"
    if y < 5:
        return "2-5y"
    if y < 10:
        return "5-10y"
    return "10y+"


df["country"] = df.apply(_resolve_country, axis=1)
df["duration_bucket_4t"] = df["years_to_maturity"].apply(_make_duration_bucket)

# ---- filters -------------------------------------------------------------

r1c1, r1c2, r1c3, r1c4 = st.columns(4)
with r1c1:
    issuer_filter = st.multiselect(
        "Issuer type",
        sorted(df["issuer_type"].dropna().unique()),
        default=(
            ["Government"] if "Government" in df["issuer_type"].values else None
        ),
    )
with r1c2:
    ccy_filter = st.multiselect(
        "Currency",
        sorted(df["currency"].dropna().unique()),
        default=["EUR"] if "EUR" in df["currency"].values else None,
    )
with r1c3:
    country_options = sorted([c for c in df["country"].dropna().unique() if c])
    country_filter = st.multiselect("Sovereign nation", country_options)
with r1c4:
    dur_bucket_filter = st.multiselect(
        "Duration bucket",
        DURATION_BUCKETS,
        help="Bucket per anni a scadenza",
    )

r2c1, r2c2, r2c3, r2c4 = st.columns(4)
with r2c1:
    min_y = st.number_input("Min net yield (%)", value=0.0, step=0.1)
with r2c2:
    max_y = st.number_input("Max net yield (%)", value=15.0, step=0.5)
with r2c3:
    min_dur = st.number_input("Min years", value=0.0, step=0.5)
with r2c4:
    max_dur = st.number_input("Max years", value=30.0, step=1.0)

ck1, ck2, _ = st.columns([1, 1, 2])
with ck1:
    exclude_callable = st.checkbox("Escludi callable", value=True)
with ck2:
    exclude_inflation = st.checkbox("Escludi inflation-linked", value=True)

mask = pd.Series(True, index=df.index)
if issuer_filter:
    mask &= df["issuer_type"].isin(issuer_filter)
if ccy_filter:
    mask &= df["currency"].isin(ccy_filter)
if country_filter:
    mask &= df["country"].isin(country_filter)
if dur_bucket_filter:
    mask &= df["duration_bucket_4t"].isin(dur_bucket_filter)
mask &= df["net_yield_pa"].between(min_y, max_y, inclusive="both")
mask &= df["years_to_maturity"].between(min_dur, max_dur, inclusive="both")
if exclude_callable and "is_callable" in df.columns:
    mask &= ~df["is_callable"].fillna(False)
if exclude_inflation and "inflation_linked" in df.columns:
    mask &= ~df["inflation_linked"].fillna(False)

view = df[mask].sort_values("net_yield_pa", ascending=False)
st.metric("Bond filtrati", len(view))

# ---- table ---------------------------------------------------------------

cols = [
    "isin",
    "name",
    "issuer_type",
    "currency",
    "country",
    "coupon",
    "latest_price",
    "net_yield_pa",
    "years_to_maturity",
    "duration_bucket_4t",
    "is_callable",
    "inflation_linked",
    "maturity_date",
]
cols = [c for c in cols if c in view.columns]
st.dataframe(
    view[cols],
    use_container_width=True,
    hide_index=True,
    column_config={
        "net_yield_pa": st.column_config.NumberColumn(
            "Net Yield (%)", format="%.2f"
        ),
        "years_to_maturity": st.column_config.NumberColumn(
            "Years", format="%.1f"
        ),
        "coupon": st.column_config.NumberColumn("Coupon (%)", format="%.2f"),
        "latest_price": st.column_config.NumberColumn("Price", format="%.2f"),
        "duration_bucket_4t": st.column_config.TextColumn("Duration bucket"),
        "country": st.column_config.TextColumn("Country"),
    },
    height=500,
)

# ---- chart ---------------------------------------------------------------

st.subheader("Yield curve (filtrato)")
if not view.empty:
    chart_df = view.dropna(subset=["years_to_maturity", "net_yield_pa"])
    if not chart_df.empty:
        color_col = "country" if "country" in chart_df.columns else "issuer_type"
        fig = px.scatter(
            chart_df,
            x="years_to_maturity",
            y="net_yield_pa",
            color=color_col,
            hover_data=["name", "isin", "coupon", "latest_price"],
            title="Net yield vs. anni a scadenza",
        )
        fig.update_layout(
            template="plotly_white",
            height=500,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#888888"),
        )
        st.plotly_chart(fig, use_container_width=True)
