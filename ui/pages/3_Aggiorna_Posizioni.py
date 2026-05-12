"""Aggiorna Posizioni — workflow per chi ha già investimenti.

Manual entry for bonds + ETFs. Writes to the unified PositionTracker.
Shows the current asset allocation derived from the entered positions.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

# --- bootstrap ---
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# ---

from portfolio.position_tracker import PositionTracker
from portfolio.price_provider import PriceProvider

st.set_page_config(page_title="Aggiorna Posizioni", page_icon="📥", layout="wide")
st.title("📥 Aggiorna posizioni esistenti")
st.markdown(
    "Inserisci manualmente bond e ETF che hai già acquistato. Il sistema "
    "calcola la tua attuale asset allocation."
)

tracker = PositionTracker()

tab_b, tab_e, tab_a = st.tabs(["💰 Bonds", "🌍 Equity ETF", "🎯 Alternative"])

# ----- BONDS -----

with tab_b:
    st.subheader("Inserisci un bond posseduto")

    with st.form("add_bond_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            isin = st.text_input("ISIN", placeholder="IT0005XXXXXX")
            name = st.text_input("Descrizione", placeholder="BTP 4.5% 2030")
            issuer = st.text_input(
                "Emittente",
                placeholder="Repubblica Italiana",
                help="Per i governativi italiani: 'Repubblica Italiana'.",
            )
        with c2:
            quantity = st.number_input(
                "Quantità (nominal €)", min_value=1000.0, step=1000.0, value=10_000.0
            )
            avg_price = st.number_input(
                "Prezzo medio acquisto (% face)", value=100.0, step=0.01, format="%.2f"
            )
            purchase_date = st.date_input("Data acquisto", value=date.today())
        with c3:
            maturity_date = st.date_input(
                "Data scadenza",
                value=date(date.today().year + 5, 1, 15),
            )
            coupon_pct = st.number_input(
                "Cedola annuale (%)", value=3.0, step=0.01, format="%.2f"
            )
            ytm_pct = st.number_input(
                "YTM all'acquisto (%, opzionale)", value=0.0, step=0.01, format="%.2f"
            )
            rating = st.text_input("Rating (opzionale)", placeholder="BBB")

        if st.form_submit_button("➕ Aggiungi bond", type="primary"):
            if not isin:
                st.error("ISIN obbligatorio.")
            else:
                tracker.add_bond(
                    isin=isin,
                    name=name or isin,
                    quantity=quantity,
                    avg_purchase_price=avg_price,
                    purchase_date=purchase_date,
                    issuer=issuer or None,
                    maturity_date=maturity_date,
                    coupon_rate=coupon_pct / 100.0,
                    coupon_frequency=1,
                    ytm_at_purchase=(ytm_pct / 100.0 if ytm_pct > 0 else None),
                    rating=rating or None,
                )
                st.success(f"✅ Aggiunto: {name or isin}")
                st.rerun()

    bonds = tracker.get_by_asset_class("bond")
    if bonds:
        st.subheader(f"Bond nel portfolio ({len(bonds)})")
        df = pd.DataFrame([p.to_dict() for p in bonds])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Nessun bond ancora inserito.")

# ----- EQUITY -----

with tab_e:
    st.subheader("Inserisci un ETF posseduto")

    with st.form("add_equity_form"):
        c1, c2 = st.columns(2)
        with c1:
            e_isin = st.text_input(
                "ISIN ETF", placeholder="IE00BK5BQT80 (VWCE)"
            )
            e_name = st.text_input(
                "Nome ETF", placeholder="Vanguard FTSE All-World"
            )
        with c2:
            e_qty = st.number_input("Quote possedute", min_value=1, step=1, value=10)
            e_price = st.number_input(
                "Prezzo medio acquisto (€/quota)",
                min_value=0.01,
                step=0.01,
                value=120.0,
                format="%.2f",
            )
            e_date = st.date_input(
                "Data acquisto", value=date.today(), key="eq_date"
            )

        if st.form_submit_button("➕ Aggiungi ETF", type="primary"):
            if not e_isin:
                st.error("ISIN obbligatorio.")
            else:
                tracker.add_equity(
                    isin=e_isin,
                    name=e_name or e_isin,
                    quantity=e_qty,
                    avg_purchase_price=e_price,
                    purchase_date=e_date,
                )
                st.success(f"✅ Aggiunto: {e_name or e_isin}")
                st.rerun()

    eq = tracker.get_by_asset_class("equity")
    if eq:
        st.subheader(f"ETF nel portfolio ({len(eq)})")
        df = pd.DataFrame([p.to_dict() for p in eq])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Nessun ETF ancora inserito.")

# ----- ALTERNATIVE -----

with tab_a:
    st.info(
        "Le strategie alternative si attivano dalla pagina "
        "**🎯 Alternative Strategies** del menù laterale. Da lì puoi "
        "registrare la posizione associata a una strategia attiva."
    )
    alt = tracker.get_by_asset_class("alternative")
    if alt:
        st.subheader(f"Strategie alternative attive ({len(alt)})")
        df = pd.DataFrame([p.to_dict() for p in alt])
        st.dataframe(
            df[["isin", "name", "strategy_id", "quantity", "avg_purchase_price", "purchase_date"]],
            use_container_width=True,
            hide_index=True,
        )

# ----- live allocation -----

st.markdown("---")
st.subheader("📊 Asset allocation attuale")

positions = tracker.get_all()
if positions:
    prices = PriceProvider().get_prices(positions)
    values = tracker.current_value_eur(prices)
    total = values["total"] or 1.0
    a, b, c, d = st.columns(4)
    a.metric(
        "💰 Bonds",
        f"€{values['bond']:,.0f}",
        f"{values['bond'] / total * 100:.1f}%",
    )
    b.metric(
        "🌍 Equity",
        f"€{values['equity']:,.0f}",
        f"{values['equity'] / total * 100:.1f}%",
    )
    c.metric(
        "🎯 Alternative",
        f"€{values['alternative']:,.0f}",
        f"{values['alternative'] / total * 100:.1f}%",
    )
    d.metric("📊 Totale", f"€{values['total']:,.0f}")
else:
    st.info("Inserisci almeno una posizione per vedere l'asset allocation.")
