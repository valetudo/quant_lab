"""Streamlit entry point for Quant Lab.

Run:
    streamlit run ui/main.py

Multi-page apps mount this file as the root; per-page logic lives under
``ui/pages/``. The root page redirects to the Home landing.
"""

from __future__ import annotations

# --- sys.path bootstrap ---
# Streamlit launches pages without going through pip install, so we insert
# the project root so `from core...`, `from strategies...` etc. resolve.
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# --- end bootstrap ---

import streamlit as st

st.set_page_config(
    page_title="Quant Lab",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📈 Quant Lab")
st.caption("Strumento personale di gestione portfolio multi-asset.")

# Bounce to Home; the user can still pick any page from the sidebar.
try:
    st.switch_page("pages/0_Home.py")
except Exception:
    # Older Streamlit versions might not support switch_page from main.
    st.info(
        "Apri la pagina **🏠 Home** dal menù laterale per iniziare. "
        "Da lì puoi scegliere se costruire il portfolio o aggiornare le posizioni esistenti."
    )
