"""Quant Lab — main entry (v3.1.0 bonds simplification).

Sidebar collapses further from v3.0.0's 4 voices to a new set of 4:

```
💰 Bonds          (default landing — was Bonds Screener + refresh)
🏗️ Ladder Builder (extracted from the old Bond Ladder unified page)
🌍 Equity
🎯 Alternative
```

The old "Bond Ladder & Builder" unified page (with tabs Tracker + Builder)
is archived. The Tracker tab content went away entirely (no portfolio
management active in v3.x); the Builder tab became its own page.

Portfolio-management pages (Portfolio Overview, Aggiorna Posizioni,
Costruisci Portfolio) plus the diagnostic pages (Backtest Lab, Data
Status, Debug Logs) keep ``visibility="hidden"`` so they stay
reachable via direct URL but disappear from the sidebar.
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

bonds = st.Page(
    "pages/4_Bonds.py",
    title="Bonds",
    icon="💰",
    default=True,
)

ladder_builder = st.Page(
    "pages/13_Ladder_Builder.py",
    title="Ladder Builder",
    icon="🏗️",
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
        bonds,
        ladder_builder,
        equity,
        alternative,
        # Hidden — kept in nav for st.switch_page targeting + URL routing.
        hidden_portfolio_overview,
        hidden_costruisci,
        hidden_aggiorna,
        hidden_backtest_lab,
        hidden_data_status,
        hidden_debug_logs,
    ]
)


# ---------- sidebar footer ----------

with st.sidebar:
    st.markdown("---")
    st.caption(
        "**Quant Lab v3.1.0**  \n"
        "Research framework + decision tools.  \n"
        "Portfolio management via broker API: TBD."
    )


pg.run()
