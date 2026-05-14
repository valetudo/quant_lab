"""Quant Lab — main entry (v3.0.0 simplification).

Sidebar collapses to 4 voices:

```
💰 Bond Ladder       (default landing)
🌍 Equity
🎯 Alternative
🛠️ Strumenti
```

Portfolio-management pages (Portfolio Overview, Aggiorna Posizioni,
Costruisci Portfolio) are registered with ``visibility="hidden"`` —
they stay reachable via direct URL but disappear from the sidebar.
This is reversible: when the broker-API integration lands, flip
``visibility`` back to ``"visible"`` and the workflow is restored.

The Backtest Lab also stays hidden but reachable; the Alternative
hub provides a one-click link per strategy.
"""

from __future__ import annotations

# --- sys.path bootstrap ---
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# --- end bootstrap ---

import streamlit as st


# ---------- visible pages (the 4-voice sidebar) ----------

bond_ladder = st.Page(
    "pages/4_Bonds_Ladder.py",
    title="Bond Ladder",
    icon="💰",
    default=True,
)

equity = st.Page(
    "pages/5_Equity_World_ETF.py",
    title="Equity",
    icon="🌍",
)

alternative = st.Page(
    "pages/6_Alternative_Strategies.py",
    title="Alternative",
    icon="🎯",
)

strumenti = st.Page(
    "pages/7_Strumenti.py",
    title="Strumenti",
    icon="🛠️",
)


# ---------- hidden pages (live + URL-reachable, not in sidebar) ----------

hidden_portfolio_overview = st.Page(
    "pages/1_Portfolio_Overview.py",
    title="Portfolio Overview",
    icon="📊",
    url_path="portfolio-overview",
    visibility="hidden",
)

hidden_costruisci = st.Page(
    "pages/2_Costruisci_Portfolio.py",
    title="Costruisci Portfolio",
    icon="🏗️",
    url_path="costruisci-portfolio",
    visibility="hidden",
)

hidden_aggiorna = st.Page(
    "pages/3_Aggiorna_Posizioni.py",
    title="Aggiorna Posizioni",
    icon="📥",
    url_path="aggiorna-posizioni",
    visibility="hidden",
)

hidden_backtest_lab = st.Page(
    "pages/9_Backtest_Lab.py",
    title="Backtest Lab",
    icon="🔬",
    url_path="backtest-lab",
    visibility="hidden",
)

hidden_bonds_screener = st.Page(
    "pages/10_Bonds_Screener.py",
    title="Bonds Screener",
    icon="🔍",
    url_path="bonds-screener",
    visibility="hidden",
)

hidden_data_status = st.Page(
    "pages/11_Data_Status.py",
    title="Data Status",
    icon="📁",
    url_path="data-status",
    visibility="hidden",
)

hidden_debug_logs = st.Page(
    "pages/12_Debug_Logs.py",
    title="Debug Logs",
    icon="🐛",
    url_path="debug-logs",
    visibility="hidden",
)


# ---------- navigation ----------

pg = st.navigation(
    [
        bond_ladder,
        equity,
        alternative,
        strumenti,
        # Hidden pages are passed in too so st.switch_page can target them.
        hidden_portfolio_overview,
        hidden_costruisci,
        hidden_aggiorna,
        hidden_backtest_lab,
        hidden_bonds_screener,
        hidden_data_status,
        hidden_debug_logs,
    ]
)


# ---------- sidebar footer ----------

with st.sidebar:
    st.markdown("---")
    st.caption(
        "**Quant Lab v3.0.0**  \n"
        "Research framework + decision tools.  \n"
        "Portfolio management via broker API: TBD."
    )


pg.run()
