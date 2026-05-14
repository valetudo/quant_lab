"""Home — landing page. Binary choice: build from scratch or update existing.

This is the entry-point for v2.0.0's "operational tool" UX. Power-user
pages (Backtest Lab, Data Status, Debug Logs) still appear in the
sidebar but the workflow is driven from here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# --- bootstrap ---
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# ---

from portfolio.position_tracker import PositionTracker
from portfolio.price_provider import PriceProvider

st.set_page_config(
    page_title="Quant Lab — Home",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🏠 Quant Lab")
st.caption("Strumento personale di gestione portfolio multi-asset")

tracker = PositionTracker()
positions = tracker.get_all()
has_positions = len(positions) > 0

st.markdown("---")

if has_positions:
    st.success(
        f"✅ Hai **{len(positions)} posizioni** registrate. Puoi continuare ad "
        f"aggiornarle o aggiungere nuove asset class."
    )
else:
    st.info(
        "👋 Benvenuto! Il portfolio è vuoto. Costruiscilo da zero, oppure "
        "carica le posizioni che hai già."
    )

st.markdown("---")
st.subheader("Cosa vuoi fare?")

col1, col2 = st.columns(2)

with col1:
    st.markdown(
        """
### 🏗️ Costruisci portfolio da zero

Hai liquidità da allocare e vuoi costruire il portfolio passo per passo.

1. Decidi le percentuali di asset allocation (bond / equity / alternative).
2. Costruisci ciascuna sezione una alla volta:
   - 💰 **Bonds** — il Ladder Builder genera una proposta di acquisto.
   - 🌍 **Equity** — guida alla scelta dell'ETF World ottimale.
   - 🎯 **Alternative** — strategie da validare prima di mettere capitale.
"""
    )
    if st.button(
        "🏗️ Inizia costruzione",
        type="primary",
        use_container_width=True,
        key="btn_build",
    ):
        st.session_state["workflow"] = "build_from_scratch"
        st.session_state["build_step"] = "allocation"
        st.switch_page("pages/2_Costruisci_Portfolio.py")

with col2:
    st.markdown(
        """
### 📥 Aggiorna posizioni esistenti

Hai già acquistato bond e/o ETF e vuoi tracciarli nel sistema.

1. Inserisci manualmente le posizioni (ISIN, quantità, prezzo medio acquisto).
2. Il sistema calcola la tua attuale asset allocation.
3. Da Portfolio Overview vedi performance, P&L, e drift dalle target.
"""
    )
    if st.button(
        "📥 Aggiorna posizioni", use_container_width=True, key="btn_update"
    ):
        st.session_state["workflow"] = "update_existing"
        st.switch_page("pages/3_Aggiorna_Posizioni.py")

# ----- quick stats -----

if has_positions:
    st.markdown("---")
    st.subheader("Stato attuale")
    prices = PriceProvider().get_prices(positions)
    values = tracker.current_value_eur(prices)

    a, b, c, d = st.columns(4)
    total = values["total"] or 1.0
    a.metric(
        "💰 Bonds",
        f"€{values['bond']:,.0f}",
        delta=f"{values['bond'] / total * 100:.0f}% del totale",
        delta_color="off",
    )
    b.metric(
        "🌍 Equity",
        f"€{values['equity']:,.0f}",
        delta=f"{values['equity'] / total * 100:.0f}% del totale",
        delta_color="off",
    )
    c.metric(
        "🎯 Alternative",
        f"€{values['alternative']:,.0f}",
        delta=f"{values['alternative'] / total * 100:.0f}% del totale",
        delta_color="off",
    )
    d.metric("📊 Totale", f"€{values['total']:,.0f}")

    if st.button("📊 Vai a Portfolio Overview per dettagli"):
        st.switch_page("pages/1_Portfolio_Overview.py")

st.markdown("---")
st.caption(
    "💡 Quant Lab è uno strumento personale. Non sostituisce consulenza "
    "finanziaria professionale. Le decisioni di investimento sono sempre tue."
)
