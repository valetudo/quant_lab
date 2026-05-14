"""Costruisci Portfolio — workflow per nuovi investitori.

Step 1: decide free-form asset allocation (bond / equity / alternative %).
Step 2: drill into each section. Each section has a dedicated page that
the user can return from at any time.
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

st.set_page_config(page_title="Costruisci Portfolio", page_icon="🏗️", layout="wide")
st.title("🏗️ Costruisci il tuo Portfolio")
mode_badge(
    "hidden",
    "Pagina hidden in v3.0.0: il portfolio management completo sarà riattivato "
    "in futuro con l'integrazione API broker.",
)
st.caption("Workflow guidato per nuovi investitori. Tre sezioni, una alla volta.")

if "build_step" not in st.session_state:
    st.session_state["build_step"] = "allocation"

# ===== STEP 1 =====

if st.session_state["build_step"] == "allocation":
    st.subheader("Step 1 di 2 — Decidi l'asset allocation")

    st.markdown(
        """
Quanto del capitale vuoi destinare a ciascuna asset class? Le percentuali
devono sommare a 100%.

**Suggerimento**: una struttura comune è **50/30/20** (bond / equity / alternative),
ma puoi adattare ai tuoi obiettivi. Più bond = più stabilità + cash flow;
più equity = più crescita di lungo termine; più alternative = più rischio
e gestione attiva richiesta.
"""
    )

    total_capital = st.number_input(
        "Capitale totale da allocare (€)",
        min_value=10_000,
        max_value=10_000_000,
        value=int(st.session_state.get("total_capital", 100_000)),
        step=10_000,
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        bonds_pct = st.slider(
            "💰 Bond %",
            0,
            100,
            int(st.session_state.get("bonds_pct", 50)),
            key="slider_bonds",
        )
    with c2:
        equity_pct = st.slider(
            "🌍 Equity %",
            0,
            100,
            int(st.session_state.get("equity_pct", 30)),
            key="slider_equity",
        )
    with c3:
        alt_pct = st.slider(
            "🎯 Alternative %",
            0,
            100,
            int(st.session_state.get("alt_pct", 20)),
            key="slider_alt",
        )

    total_pct = bonds_pct + equity_pct + alt_pct

    if total_pct != 100:
        st.error(f"⚠️ Le percentuali devono sommare a 100% (ora: {total_pct}%)")
    else:
        st.success(
            f"✅ Allocazione: "
            f"€{total_capital * bonds_pct / 100:,.0f} Bond + "
            f"€{total_capital * equity_pct / 100:,.0f} Equity + "
            f"€{total_capital * alt_pct / 100:,.0f} Alternative"
        )

        if st.button("Continua →", type="primary"):
            st.session_state["total_capital"] = total_capital
            st.session_state["bonds_pct"] = bonds_pct
            st.session_state["equity_pct"] = equity_pct
            st.session_state["alt_pct"] = alt_pct
            st.session_state["build_step"] = "sections"
            st.rerun()

# ===== STEP 2 =====

elif st.session_state["build_step"] == "sections":
    st.subheader("Step 2 di 2 — Costruisci ogni sezione")

    total = st.session_state["total_capital"]
    bonds_budget = total * st.session_state["bonds_pct"] / 100
    equity_budget = total * st.session_state["equity_pct"] / 100
    alt_budget = total * st.session_state["alt_pct"] / 100

    st.markdown(
        f"Hai €{total:,.0f} totali. Apri una sezione alla volta — le posizioni "
        f"vengono salvate automaticamente nel Portfolio Tracker."
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("### 💰 Bonds")
        st.metric("Budget allocato", f"€{bonds_budget:,.0f}")
        st.markdown(
            "Ladder con composizione mista (BTP italiani, corporate, gov esteri). "
            "Il Ladder Builder genera una proposta concreta di acquisto."
        )
        if st.button(
            "Costruisci Bonds →",
            type="primary",
            use_container_width=True,
            key="b_bonds",
        ):
            st.session_state["build_bonds_budget"] = bonds_budget
            st.switch_page("pages/4_Bonds_Ladder.py")

    with c2:
        st.markdown("### 🌍 Equity")
        st.metric("Budget allocato", f"€{equity_budget:,.0f}")
        st.markdown(
            "ETF passivo globale (FTSE All-World). Massima diversificazione "
            "geografica con costi minimi. Guida alla scelta dell'ETF ottimale."
        )
        if st.button(
            "Costruisci Equity →",
            type="primary",
            use_container_width=True,
            key="b_equity",
        ):
            st.session_state["build_equity_budget"] = equity_budget
            st.switch_page("pages/5_Equity_World_ETF.py")

    with c3:
        st.markdown("### 🎯 Alternative")
        st.metric("Budget allocato", f"€{alt_budget:,.0f}")
        st.markdown(
            "Strategie attive da validare (Pattern Finder e future). Richiede "
            "walk-forward + benchmark prima di deploy. Solo per power users."
        )
        if st.button(
            "Esplora Alternative →", use_container_width=True, key="b_alt"
        ):
            st.switch_page("pages/6_Alternative_Strategies.py")

    st.markdown("---")
    if st.button("← Cambia allocation"):
        st.session_state["build_step"] = "allocation"
        st.rerun()
