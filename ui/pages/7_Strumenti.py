"""Strumenti — power-user features hub.

Discovery shortcut for the diagnostic / advanced pages. The pages
themselves are still individually visible in the sidebar (Streamlit puts
every file in `pages/` there), but new users land here first and decide
which they need.
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

st.set_page_config(page_title="Strumenti", page_icon="🛠️", layout="wide")
st.title("🛠️ Strumenti")
st.caption("Diagnostica e funzioni avanzate. Non servono per uso quotidiano.")

st.markdown("---")

c1, c2, c3 = st.columns(3)

with c1:
    st.markdown("### 🔬 Backtest Lab")
    st.caption(
        "Esegui backtest di strategie attive (es. Pattern Finder). "
        "**Non usare per validare ETF passivi o bond ladder.**"
    )
    if st.button("Apri Backtest Lab", use_container_width=True):
        st.switch_page("pages/9_Backtest_Lab.py")

    st.markdown("")
    st.markdown("### 🔍 Bonds Screener")
    st.caption(
        "Esplora il database bond di Borsa Italiana con filtri liberi "
        "(rendimento, scadenza, emittente)."
    )
    if st.button("Apri Bonds Screener", use_container_width=True):
        st.switch_page("pages/10_Bonds_Screener.py")

    st.markdown("")
    st.markdown("### 🏗️ Ladder Builder")
    st.caption(
        "Generatore di proposte di acquisto bond ladder (parametri: budget, "
        "n gradini, duration max). Accessibile anche da Bonds — Ladder."
    )
    if st.button("Apri Ladder Builder", use_container_width=True):
        st.switch_page("pages/8_Ladder_Builder.py")

with c2:
    st.markdown("### 📁 Data Status")
    st.caption(
        "Stato delle data source: copertura prezzi FMP, snapshot bonds.db, "
        "freschezza degli archivi."
    )
    if st.button("Apri Data Status", use_container_width=True):
        st.switch_page("pages/11_Data_Status.py")

    st.markdown("")
    st.markdown("### 🐛 Debug Logs")
    st.caption("Log runtime e di migrazione.")
    if st.button("Apri Debug Logs", use_container_width=True):
        st.switch_page("pages/12_Debug_Logs.py")

with c3:
    st.markdown("### 📚 Documentazione")
    st.caption(
        "Architettura, guide per aggiungere una strategia, decision records "
        "delle scelte di sleeve."
    )
    st.markdown(
        "- `README.md` — overview\n"
        "- `docs/architecture.md` — modello del sistema\n"
        "- `docs/adding_a_strategy.md` — aggiungere strategie\n"
        "- `CHANGELOG.md` — storico release\n"
        "- `_migration_log/` — decision records"
    )

st.markdown("---")

st.info(
    "💡 **Quando usare il Backtest Lab?** Solo per testare strategie **alternative "
    "attive** prima di deployarle (Pattern Finder, future strategie da sviluppare). "
    "Per asset passivi (bond ladder, ETF World) NON serve un backtest — la scelta "
    "è di natura strategica/strutturale, non statistica."
)
