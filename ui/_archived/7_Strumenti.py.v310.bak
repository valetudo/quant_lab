"""Strumenti — contenitore minimalista per utility tecniche (v3.0.0).

Three buttons that switch_page to the underlying hidden pages
(Bonds Screener, Data Status, Debug Logs). An expander below exposes
the portfolio-management pages that have been demoted from the nav.
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

from ui.components.mode_badge import mode_badge

st.set_page_config(page_title="Strumenti", page_icon="🛠️", layout="wide")

st.title("🛠️ Strumenti")
mode_badge("ricerca", "Utility tecniche. Solo lettura / diagnostica.")
st.markdown(
    "Strumenti accessori del sistema. Utili per ispezione dati e debugging — "
    "non servono per uso quotidiano."
)

st.markdown("---")

c1, c2, c3 = st.columns(3)

with c1:
    st.markdown("### 🔍 Bonds Screener")
    st.caption(
        "Esplora il catalogo `bonds.db` con filtri (yield, rating, scadenza, "
        "emittente). Utile per ricerca individuale di bond fuori dal context "
        "della ladder."
    )
    if st.button("Apri Bonds Screener", use_container_width=True, key="open_bs"):
        st.switch_page("pages/10_Bonds_Screener.py")

with c2:
    st.markdown("### 📁 Data Status")
    st.caption(
        "Stato delle data source: ultimi update FMP cache, bonds.db, snapshot "
        "Directa imports. Diagnostica freshness dei dati di mercato."
    )
    if st.button("Apri Data Status", use_container_width=True, key="open_ds"):
        st.switch_page("pages/11_Data_Status.py")

with c3:
    st.markdown("### 🐛 Debug Logs")
    st.caption(
        "Log runtime, errori, traceback. Utile per troubleshooting di problemi "
        "operativi o regressioni."
    )
    if st.button("Apri Debug Logs", use_container_width=True, key="open_dl"):
        st.switch_page("pages/12_Debug_Logs.py")

st.markdown("---")

# ----- hidden pages section -----

with st.expander("🔒 Pagine portfolio management (nascoste in v3.0.0)"):
    st.markdown(
        """
Le pagine di portfolio management sono ancora live nel codice ma non più nella
navigation principale. Saranno **riattivate in futuro** quando integreremo le
API broker (Directa / IBKR) per portfolio tracking automatico — a quel punto
il workflow manuale diventerà obsoleto.

Per ora restano accessibili via URL diretto o dai bottoni qui sotto.
"""
    )

    h1, h2, h3 = st.columns(3)
    with h1:
        if st.button("📊 Portfolio Overview", use_container_width=True, key="open_po"):
            st.switch_page("pages/1_Portfolio_Overview.py")
    with h2:
        if st.button("🏗️ Costruisci Portfolio", use_container_width=True, key="open_cp"):
            st.switch_page("pages/2_Costruisci_Portfolio.py")
    with h3:
        if st.button("📥 Aggiorna Posizioni", use_container_width=True, key="open_ap"):
            st.switch_page("pages/3_Aggiorna_Posizioni.py")

    st.caption(
        "💡 Queste pagine funzionano ancora completamente, ma il workflow "
        "manuale di portfolio management non è più il focus operativo in v3.0.0. "
        "Vedi `_migration_log/V3_0_0_SIMPLIFICATION.md` per la motivazione."
    )

st.markdown("---")

# ----- backtest lab also hidden -----

with st.expander("🔬 Backtest Lab (anche hidden)"):
    st.markdown(
        "Il **Backtest Lab** completo (UI streaming, walk-forward, benchmark "
        "comparison) è ora hidden dalla nav primaria — viene aperto dall'interno "
        "di **🎯 Alternative** per ciascuna strategia."
    )
    if st.button("🔬 Apri Backtest Lab", use_container_width=True, key="open_bl"):
        st.switch_page("pages/9_Backtest_Lab.py")
