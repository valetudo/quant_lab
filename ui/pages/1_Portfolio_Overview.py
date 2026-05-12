"""Portfolio Overview — performance tracker delle posizioni reali (v2.0.0).

NON è un backtest. Mostra: valore corrente del portfolio (con prezzi più
recenti disponibili), P&L per posizione e aggregato per asset class,
distribuzione attuale. La logica di drift / target allocation è opt-in
(richiede che l'utente definisca un target — non più hard-coded a 50/30/20).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# --- bootstrap ---
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# ---

from portfolio.position_tracker import PositionTracker
from portfolio.price_provider import PriceProvider

st.set_page_config(page_title="Portfolio Overview", page_icon="📊", layout="wide")

st.title("📊 Portfolio Overview")
st.caption("Performance reale delle tue posizioni attuali. Non è un backtest.")

tracker = PositionTracker()
positions = tracker.get_all()

if not positions:
    st.warning(
        "⚠️ Nessuna posizione nel portfolio. Inizia dalla pagina **🏠 Home** "
        "(Costruisci o Aggiorna)."
    )
    st.stop()

prices = PriceProvider().get_prices(positions)
pnl_df = tracker.unrealized_pnl(prices)
values = tracker.current_value_eur(prices)

# ----- headline -----

st.subheader("Stato corrente")
total_cost = float(pnl_df["cost_basis_eur"].sum()) if not pnl_df.empty else 0.0
total_current = float(pnl_df["current_value_eur"].sum()) if not pnl_df.empty else 0.0
total_pnl = total_current - total_cost
total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Valore totale",
    f"€{total_current:,.0f}",
    delta=f"€{total_pnl:+,.0f} ({total_pnl_pct:+.2f}%)",
)
total_for_pct = total_current or 1.0
c2.metric(
    "💰 Bonds",
    f"€{values['bond']:,.0f}",
    f"{values['bond'] / total_for_pct * 100:.1f}%",
)
c3.metric(
    "🌍 Equity",
    f"€{values['equity']:,.0f}",
    f"{values['equity'] / total_for_pct * 100:.1f}%",
)
c4.metric(
    "🎯 Alternative",
    f"€{values['alternative']:,.0f}",
    f"{values['alternative'] / total_for_pct * 100:.1f}%",
)

n_stale = int(pnl_df["price_is_stale"].sum()) if not pnl_df.empty else 0
if n_stale > 0:
    st.caption(
        f"ℹ️ {n_stale} posizioni mostrano il prezzo medio d'acquisto come "
        f"fallback perché nessun prezzo aggiornato è disponibile in cache."
    )

st.markdown("---")

# ----- pie + summary -----

st.subheader("Distribuzione attuale")
left, right = st.columns([1, 2])

with left:
    if total_current > 0:
        fig_pie = go.Figure(
            data=[
                go.Pie(
                    labels=["Bonds", "Equity", "Alternative"],
                    values=[
                        values["bond"],
                        values["equity"],
                        values["alternative"],
                    ],
                    hole=0.45,
                    marker=dict(colors=["#2E7D32", "#1565C0", "#F57C00"]),
                )
            ]
        )
        fig_pie.update_layout(height=300, margin=dict(t=0, b=0, l=0, r=0))
        st.plotly_chart(fig_pie, use_container_width=True)

with right:
    st.markdown("**Sintesi per asset class**")
    if not pnl_df.empty:
        summary = (
            pnl_df.groupby("asset_class")
            .agg(
                cost_basis=("cost_basis_eur", "sum"),
                current_value=("current_value_eur", "sum"),
                pnl_eur=("pnl_eur", "sum"),
            )
            .reset_index()
        )
        summary["pnl_pct"] = summary.apply(
            lambda r: (r["pnl_eur"] / r["cost_basis"] * 100) if r["cost_basis"] > 0 else 0.0,
            axis=1,
        )
        summary["asset_class"] = summary["asset_class"].map(
            {
                "bond": "💰 Bonds",
                "equity": "🌍 Equity",
                "alternative": "🎯 Alternative",
                "cash": "💵 Cash",
            }
        )
        st.dataframe(
            summary,
            column_config={
                "asset_class": "Asset class",
                "cost_basis": st.column_config.NumberColumn("Costo €", format="€%.0f"),
                "current_value": st.column_config.NumberColumn(
                    "Valore €", format="€%.0f"
                ),
                "pnl_eur": st.column_config.NumberColumn("P&L €", format="€%+.0f"),
                "pnl_pct": st.column_config.NumberColumn("P&L %", format="%+.2f%%"),
            },
            hide_index=True,
            use_container_width=True,
        )

st.markdown("---")

# ----- detail per asset class -----

st.subheader("Dettaglio per asset class")

tab_b, tab_e, tab_a = st.tabs(["💰 Bonds", "🌍 Equity", "🎯 Alternative"])

POS_COLS = {
    "isin": "ISIN",
    "name": "Nome",
    "quantity": "Quantità",
    "avg_purchase_price": "Prezzo medio acq.",
    "current_price": "Prezzo oggi",
    "cost_basis_eur": "Costo €",
    "current_value_eur": "Valore €",
    "pnl_eur": "P&L €",
    "pnl_pct": "P&L %",
    "purchase_date": "Data acq.",
}

with tab_b:
    sub = pnl_df[pnl_df["asset_class"] == "bond"]
    if not sub.empty:
        st.dataframe(
            sub[list(POS_COLS.keys())],
            column_config={
                "isin": "ISIN",
                "name": "Bond",
                "quantity": st.column_config.NumberColumn("Quantità €", format="€%.0f"),
                "avg_purchase_price": st.column_config.NumberColumn(
                    "Prezzo acq.", format="%.2f"
                ),
                "current_price": st.column_config.NumberColumn(
                    "Prezzo oggi", format="%.2f"
                ),
                "cost_basis_eur": st.column_config.NumberColumn(
                    "Costo €", format="€%.0f"
                ),
                "current_value_eur": st.column_config.NumberColumn(
                    "Valore €", format="€%.0f"
                ),
                "pnl_eur": st.column_config.NumberColumn("P&L €", format="€%+.0f"),
                "pnl_pct": st.column_config.NumberColumn(
                    "P&L %", format="%+.2f%%"
                ),
                "purchase_date": st.column_config.DateColumn(
                    "Data acq.", format="DD MMM YYYY"
                ),
            },
            use_container_width=True,
            hide_index=True,
        )
        st.info(
            "💡 Per dettagli scadenze, composizione e cash flow vai a "
            "**💰 Bonds — Ladder**."
        )
    else:
        st.info("Nessuna posizione in bonds.")

with tab_e:
    sub = pnl_df[pnl_df["asset_class"] == "equity"]
    if not sub.empty:
        st.dataframe(
            sub[list(POS_COLS.keys())],
            column_config={
                "isin": "ISIN",
                "name": "ETF",
                "quantity": st.column_config.NumberColumn("Quote", format="%d"),
                "avg_purchase_price": st.column_config.NumberColumn(
                    "Prezzo acq. €", format="€%.2f"
                ),
                "current_price": st.column_config.NumberColumn(
                    "Prezzo oggi €", format="€%.2f"
                ),
                "cost_basis_eur": st.column_config.NumberColumn(
                    "Costo €", format="€%.0f"
                ),
                "current_value_eur": st.column_config.NumberColumn(
                    "Valore €", format="€%.0f"
                ),
                "pnl_eur": st.column_config.NumberColumn("P&L €", format="€%+.0f"),
                "pnl_pct": st.column_config.NumberColumn(
                    "P&L %", format="%+.2f%%"
                ),
                "purchase_date": st.column_config.DateColumn(
                    "Data acq.", format="DD MMM YYYY"
                ),
            },
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Nessuna posizione in equity.")

with tab_a:
    sub = pnl_df[pnl_df["asset_class"] == "alternative"]
    if not sub.empty:
        st.dataframe(sub, use_container_width=True, hide_index=True)
    else:
        st.info(
            "Nessuna posizione in alternative strategies. "
            "Vai a **🎯 Alternative Strategies** per esplorare."
        )

# ----- refresh / audit log -----

st.markdown("---")
left, right = st.columns([3, 1])
with left:
    st.caption(
        "I prezzi mostrati sono gli ultimi disponibili in cache "
        "(bonds.db per i bond, FMP cache per gli ETF). Per aggiornare i prezzi "
        "vai a **🛠️ Strumenti → Data Status**."
    )
with right:
    if st.button("🔄 Ricarica"):
        st.rerun()
