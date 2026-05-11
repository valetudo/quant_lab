"""Streamlit entry point for quant_lab.

Run:
    streamlit run ui/main.py
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

from core.data.storage import DataStorage, load_global_config


def main() -> None:
    st.set_page_config(
        page_title="quant_lab",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("📈 quant_lab")
    st.caption("Strategy framework, backtest, screening and analytics.")

    cfg = load_global_config()
    storage = DataStorage.from_config(cfg)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            "DuckDB store",
            "present" if storage.duckdb_path.exists() else "missing",
            str(storage.duckdb_path),
        )
    with col2:
        st.metric(
            "Bonds DB",
            "present" if storage.bonds_db_exists() else "missing",
            str(storage.bonds_db_path),
        )
    with col3:
        st.metric("Capital (EUR)", f"{cfg.get('initial_capital_eur', 50000):,}")

    st.markdown("---")
    st.subheader("Pages")
    st.markdown(
        "- **Portfolio Overview** — multi-strategy aggregate (stub).\n"
        "- **Strategies** — list and drill-down per strategy.\n"
        "- **Backtest Runner** — pick a strategy, parameters, run.\n"
        "- **Data Status** — universe coverage and last-update.\n"
        "- **Bonds Screener** — Borsa Italiana screener UI.\n"
        "- **Debug Logs** — view migration and runtime logs."
    )

    with st.expander("Configuration"):
        st.json(cfg)


if __name__ == "__main__":
    main()
