"""Gap-analysis helper for the import workflow.

Side-by-side current vs target allocation, with action suggestions in
plain Italian. Used by ``ui/pages/3_Aggiorna_Posizioni.py`` after a
Directa import has been applied.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.data.importers.directa_xlsx import DirectaPortfolioSnapshot

# Theme-neutral colors (match ladder_viz / Portfolio Overview)
_COLOR_BOND = "#2E7D32"
_COLOR_EQUITY = "#1565C0"
_COLOR_ALT = "#F57C00"
_COLOR_CASH = "#757575"


def show_gap_analysis(
    snapshot: DirectaPortfolioSnapshot,
    *,
    key_prefix: str = "gap",
    default_bond_pct: int = 50,
    default_equity_pct: int = 30,
    default_alt_pct: int = 20,
) -> None:
    """Render the current-vs-target allocation widget + actionable suggestions.

    ``snapshot`` carries the broker positions plus the user-entered cash
    balance. The widget exposes three sliders so the user can vary the
    target on the fly without leaving the page.
    """
    st.subheader("📊 Composizione attuale vs target")

    cash = float(snapshot.cash_balance_eur or 0.0)
    totals = snapshot.total_by_asset_class_eur()
    bonds = float(totals.get("bond", 0.0))
    equity = float(totals.get("equity", 0.0))
    alternative = float(totals.get("unknown", 0.0))  # unclassified → alternative
    total = bonds + equity + alternative + cash

    if total <= 0:
        st.warning("Nessuna posizione da analizzare (patrimonio totale = €0).")
        return

    current_alloc = {
        "bond": bonds / total,
        "equity": equity / total,
        "alternative": alternative / total,
        "cash": cash / total,
    }

    st.markdown("**Imposta i tuoi target di asset allocation**")
    t1, t2, t3 = st.columns(3)
    with t1:
        tgt_bond = st.slider(
            "💰 Target Bond %",
            0,
            100,
            default_bond_pct,
            key=f"{key_prefix}_t_bond",
        )
    with t2:
        tgt_eq = st.slider(
            "🌍 Target Equity %",
            0,
            100,
            default_equity_pct,
            key=f"{key_prefix}_t_eq",
        )
    with t3:
        tgt_alt = st.slider(
            "🎯 Target Alternative %",
            0,
            100,
            default_alt_pct,
            key=f"{key_prefix}_t_alt",
        )

    sum_tgt = tgt_bond + tgt_eq + tgt_alt
    if sum_tgt != 100:
        st.warning(
            f"⚠️ I target devono sommare a 100% (ora: {sum_tgt}%). "
            f"Il delta sarà considerato cash residuo."
        )

    # ----- side-by-side pies -----

    pcol1, pcol2 = st.columns(2)
    with pcol1:
        st.markdown("**Attuale**")
        fig_cur = go.Figure(
            data=[
                go.Pie(
                    labels=["Bonds", "Equity", "Alternative", "Cash"],
                    values=[bonds, equity, alternative, cash],
                    hole=0.4,
                    marker=dict(
                        colors=[_COLOR_BOND, _COLOR_EQUITY, _COLOR_ALT, _COLOR_CASH]
                    ),
                )
            ]
        )
        fig_cur.update_layout(
            height=300,
            margin=dict(t=0, b=0, l=0, r=0),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#888888"),
        )
        st.plotly_chart(fig_cur, use_container_width=True)

    with pcol2:
        st.markdown("**Target**")
        fig_tgt = go.Figure(
            data=[
                go.Pie(
                    labels=["Bonds", "Equity", "Alternative"],
                    values=[tgt_bond, tgt_eq, tgt_alt],
                    hole=0.4,
                    marker=dict(colors=[_COLOR_BOND, _COLOR_EQUITY, _COLOR_ALT]),
                )
            ]
        )
        fig_tgt.update_layout(
            height=300,
            margin=dict(t=0, b=0, l=0, r=0),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#888888"),
        )
        st.plotly_chart(fig_tgt, use_container_width=True)

    # ----- gap table -----

    target_bond_eur = total * tgt_bond / 100
    target_eq_eur = total * tgt_eq / 100
    target_alt_eur = total * tgt_alt / 100

    rows = [
        {
            "Sleeve": "💰 Bonds",
            "Attuale €": bonds,
            "Attuale %": f"{current_alloc['bond'] * 100:.1f}%",
            "Target €": target_bond_eur,
            "Target %": f"{tgt_bond}%",
            "Gap €": target_bond_eur - bonds,
        },
        {
            "Sleeve": "🌍 Equity",
            "Attuale €": equity,
            "Attuale %": f"{current_alloc['equity'] * 100:.1f}%",
            "Target €": target_eq_eur,
            "Target %": f"{tgt_eq}%",
            "Gap €": target_eq_eur - equity,
        },
        {
            "Sleeve": "🎯 Alternative",
            "Attuale €": alternative,
            "Attuale %": f"{current_alloc['alternative'] * 100:.1f}%",
            "Target €": target_alt_eur,
            "Target %": f"{tgt_alt}%",
            "Gap €": target_alt_eur - alternative,
        },
        {
            "Sleeve": "💵 Cash",
            "Attuale €": cash,
            "Attuale %": f"{current_alloc['cash'] * 100:.1f}%",
            "Target €": 0.0,
            "Target %": "0%",
            "Gap €": -cash,
        },
    ]
    gap_df = pd.DataFrame(rows)

    st.dataframe(
        gap_df,
        column_config={
            "Sleeve": st.column_config.TextColumn("Sleeve"),
            "Attuale €": st.column_config.NumberColumn("Attuale €", format="€%.0f"),
            "Target €": st.column_config.NumberColumn("Target €", format="€%.0f"),
            "Gap €": st.column_config.NumberColumn(
                "Gap €",
                format="€%+.0f",
                help=(
                    "Quanto serve per arrivare al target. "
                    "Positivo = devi comprare. Negativo = devi vendere o redistribuire."
                ),
            ),
        },
        hide_index=True,
        use_container_width=True,
    )

    # ----- actionable suggestions -----

    st.markdown("**🎯 Azioni suggerite**")
    bond_gap = target_bond_eur - bonds
    eq_gap = target_eq_eur - equity
    alt_gap = target_alt_eur - alternative

    threshold_eur = max(1000.0, total * 0.01)  # ignore tiny drifts (~1% of total)
    suggestions: list[tuple[str, str]] = []

    if cash > total * 0.05:
        suggestions.append(
            (
                "info",
                f"💵 Hai **€{cash:,.0f}** di liquidità da investire "
                f"({current_alloc['cash'] * 100:.1f}% del patrimonio).",
            )
        )

    if bond_gap > threshold_eur:
        suggestions.append(
            (
                "info",
                f"💰 **Bonds**: ti mancano **€{bond_gap:,.0f}** per arrivare al target. "
                f"Apri il **🏗️ Ladder Builder** per generare una proposta di acquisto.",
            )
        )
    elif bond_gap < -threshold_eur:
        suggestions.append(
            (
                "warning",
                f"💰 **Bonds**: hai **€{-bond_gap:,.0f}** in eccesso. "
                f"Valuta di vendere i bond a scadenza più lunga per ribilanciare.",
            )
        )

    if eq_gap > threshold_eur:
        suggestions.append(
            (
                "info",
                f"🌍 **Equity**: ti mancano **€{eq_gap:,.0f}**. "
                f"Apri **🌍 Equity — World ETF** per acquistare VWCE.",
            )
        )
    elif eq_gap < -threshold_eur:
        suggestions.append(
            (
                "warning",
                f"🌍 **Equity**: hai **€{-eq_gap:,.0f}** in eccesso. "
                f"Valuta di ridurre la posizione.",
            )
        )

    if alt_gap > threshold_eur:
        suggestions.append(
            (
                "info",
                f"🎯 **Alternative**: hai **€{alt_gap:,.0f}** non allocati. "
                f"Apri **🎯 Alternative Strategies** se vuoi attivare strategie.",
            )
        )

    if not suggestions:
        st.success("✅ Portfolio in linea con i target. Nessuna azione necessaria.")
        return

    for level, msg in suggestions:
        if level == "warning":
            st.warning(msg)
        else:
            st.info(msg)


def show_snapshot_summary(snapshot: DirectaPortfolioSnapshot) -> None:
    """Mini header showing portfolio totals after import."""
    totals = snapshot.total_by_asset_class_eur()
    cash = float(snapshot.cash_balance_eur or 0.0)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💰 Bond", f"€{totals.get('bond', 0):,.0f}")
    c2.metric("🌍 Equity", f"€{totals.get('equity', 0):,.0f}")
    c3.metric("💵 Cash", f"€{cash:,.0f}")
    c4.metric("📊 Patrimonio", f"€{snapshot.patrimony_total_eur:,.0f}")
