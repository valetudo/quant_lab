"""Streamlit entry point for Quant Lab.

Run::

    streamlit run ui/main.py

Uses ``st.navigation`` with named sections (Streamlit ≥ 1.36) so the
sidebar groups pages by purpose rather than listing them flat. When
``st.navigation`` is invoked, Streamlit suppresses its automatic page
discovery in ``ui/pages/``, so the file list there is purely the
implementation — the displayed nav is what we declare below.

Sidebar layout:

```
🏠 Home

📁 IL MIO PORTAFOGLIO
   📊 Portfolio Overview
   📥 Aggiorna Posizioni
   🏗️ Costruisci Portfolio

🔬 STRUMENTI DI RICERCA
   💰 Bonds — Ladder & Builder
   🌍 Equity — World ETF
   🎯 Alternative Strategies
   🔍 Bonds Screener
   🔬 Backtest Lab
   📁 Data Status
```

Debug Logs is intentionally archived from the primary nav; the page
file lives in ``ui/_archived/`` and isn't reachable from the sidebar.
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

# Page declarations. Paths are relative to this entry script.
home = st.Page("pages/0_Home.py", title="Home", icon="🏠", default=True)

portfolio_overview = st.Page(
    "pages/1_Portfolio_Overview.py", title="Portfolio Overview", icon="📊"
)
aggiorna_posizioni = st.Page(
    "pages/3_Aggiorna_Posizioni.py", title="Aggiorna Posizioni", icon="📥"
)
costruisci_portfolio = st.Page(
    "pages/2_Costruisci_Portfolio.py", title="Costruisci Portfolio", icon="🏗️"
)

bonds_ladder = st.Page(
    "pages/4_Bonds_Ladder.py", title="Bonds — Ladder & Builder", icon="💰"
)
equity_world = st.Page(
    "pages/5_Equity_World_ETF.py", title="Equity — World ETF", icon="🌍"
)
alternative = st.Page(
    "pages/6_Alternative_Strategies.py", title="Alternative Strategies", icon="🎯"
)
bonds_screener = st.Page(
    "pages/10_Bonds_Screener.py", title="Bonds Screener", icon="🔍"
)
backtest_lab = st.Page("pages/9_Backtest_Lab.py", title="Backtest Lab", icon="🔬")
data_status = st.Page("pages/11_Data_Status.py", title="Data Status", icon="📁")

pg = st.navigation(
    {
        "": [home],
        "📁 IL MIO PORTAFOGLIO": [
            portfolio_overview,
            aggiorna_posizioni,
            costruisci_portfolio,
        ],
        "🔬 STRUMENTI DI RICERCA": [
            bonds_ladder,
            equity_world,
            alternative,
            bonds_screener,
            backtest_lab,
            data_status,
        ],
    }
)
pg.run()
