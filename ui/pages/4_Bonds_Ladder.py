"""Bonds — Ladder & Builder (unified, v2.2.0).

Two tabs sharing the same page:

- **📊 Tracker**: current bond ladder composition, cash-flow projection,
  gap analysis, position manager, health check. Driven by the legacy
  ``LadderTracker`` over ``data_storage/bonds/positions.parquet``.
- **🏗️ Builder**: input parameters → :class:`LadderBuilder` generates a
  concrete purchase proposal (literal ladder chart, cash-flow timeline,
  per-rung breakdown, confirmation workflow that writes through the
  tracker).

Decision support only — no live orders.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# --- bootstrap ---
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# ---

from core.data.providers.borsa_italiana_provider import BorsaItalianaProvider
from strategies.bonds_income.ladder import LadderConfig, LadderTracker
from strategies.bonds_income.ladder_builder import (
    LadderBuilder,
    LadderBuilderConfig,
    compute_next_12m_cashflow,
    format_broker_list,
)
import time as _time

from core.data.refresh_bonds import get_state as _get_refresh_state
from ui.components.bonds_refresh_progress import render_refresh_panel
from ui.utils.cache import get_storage
from ui.utils.ladder_viz import build_cashflow_timeline, build_ladder_chart

st.set_page_config(page_title="Bonds — Ladder & Builder", page_icon="💰", layout="wide")
st.title("💰 Bonds — Ladder & Builder")
st.caption(
    "Tracker della scala obbligazionaria esistente + Builder per generare nuove "
    "proposte di acquisto. Non è una trading strategy: decisione e ordini sono manuali."
)

storage = get_storage()

# ===== Bonds data freshness banner + refresh panel (shared by both tabs) =====

bonds_db = storage.bonds_db_path if hasattr(storage, "bonds_db_path") else None
_refresh_status = _get_refresh_state().status

if _refresh_status == "idle":
    # Compact layout: freshness banner left, "🔄 Aggiorna" button right.
    fs1, fs2 = st.columns([3, 1])
    with fs1:
        if bonds_db and bonds_db.exists():
            last_modified = pd.Timestamp.fromtimestamp(os.path.getmtime(bonds_db))
            age_days = (pd.Timestamp.now() - last_modified).days
            if age_days < 2:
                st.success(
                    f"✅ Dati bonds aggiornati "
                    f"({last_modified.strftime('%Y-%m-%d %H:%M')}, {age_days}g fa)"
                )
            elif age_days < 7:
                st.info(
                    f"📅 Ultimo aggiornamento bonds: {age_days} giorni fa "
                    f"({last_modified.strftime('%Y-%m-%d')})"
                )
            else:
                st.warning(
                    f"⚠️ Dati bonds stale: {age_days} giorni fa. "
                    "Aggiorna per prezzi più recenti."
                )
        else:
            st.error("❌ Database bonds non trovato. Aggiorna ora.")
    with fs2:
        _refresh_should_rerun = render_refresh_panel()
else:
    # Full-width layout: the refresh panel takes the whole row so the
    # progress bar, metrics, and cancel button get the space they need.
    _refresh_should_rerun = render_refresh_panel()

# Auto-rerun while a refresh is in progress so the user sees live progress.
if _refresh_should_rerun:
    _time.sleep(2)
    st.rerun()

st.markdown("---")

# ===== Two tabs =====

tab_tracker, tab_builder = st.tabs(["📊 Tracker", "🏗️ Builder"])


# ================================================================
#  TAB 1 — TRACKER (existing ladder + composition + gaps + manager)
# ================================================================

with tab_tracker:
    st.markdown(
        "Stato della scala obbligazionaria che hai già costruito. "
        "Composizione per bucket, cash flow previsto, identificazione gap, "
        "e gestione posizioni."
    )

    with st.expander("⚙️ Configurazione ladder (target buckets, pesi)", expanded=False):
        cc1, cc2, cc3, cc4 = st.columns(4)
        with cc1:
            n_buckets = st.slider("Maturity buckets (anni)", 5, 15, value=10)
        with cc2:
            sovereign_w = st.slider(
                "Peso sovereign", 0.0, 1.0, value=0.70, step=0.05
            )
        with cc3:
            liq_reserve = st.slider(
                "Riserva liquidità %", 0.0, 20.0, value=5.0, step=1.0
            )
        with cc4:
            max_issuer = st.slider(
                "Max concentrazione emittente %", 1.0, 25.0, value=5.0, step=0.5
            )

    cfg = LadderConfig(
        maturity_buckets_years=tuple(range(1, n_buckets + 1)),
        sovereign_weight=sovereign_w,
        corporate_weight=round(1.0 - sovereign_w, 4),
        liquidity_reserve_pct=liq_reserve,
        max_issuer_concentration_pct=max_issuer,
    )
    tracker = LadderTracker(config=cfg)
    active = tracker.active

    # ----- composition -----

    st.subheader("Composizione attuale")
    if active.empty:
        st.info(
            "Nessuna posizione registrata. Aggiungi un bond qui sotto "
            "(*Position manager*) oppure passa al tab **🏗️ Builder** "
            "per generare una proposta di acquisto."
        )

    comp = tracker.get_ladder_composition()
    if not comp.empty:
        bar_df = comp.melt(
            id_vars=["maturity_bucket", "target_pct", "current_pct"],
            value_vars=["sovereign_value_eur", "corporate_value_eur"],
            var_name="issuer_type",
            value_name="value_eur",
        )
        bar_df["issuer_type"] = bar_df["issuer_type"].map(
            {
                "sovereign_value_eur": "Government",
                "corporate_value_eur": "Corporate",
            }
        )
        fig = go.Figure()
        for it, colour in [("Government", "#1f77b4"), ("Corporate", "#ff7f0e")]:
            sub = bar_df[bar_df["issuer_type"] == it]
            fig.add_trace(
                go.Bar(
                    x=sub["maturity_bucket"],
                    y=sub["value_eur"],
                    name=it,
                    marker_color=colour,
                )
            )
        fig.update_layout(
            barmode="stack",
            template="plotly_white",
            height=340,
            title="Valore per maturity bucket",
            yaxis_title="EUR",
            xaxis_title="Maturity bucket",
            margin=dict(l=0, r=0, t=40, b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#888888"),
        )
        total_value = float(comp["total_value_eur"].sum())
        if total_value > 0:
            per_bucket_target = total_value / len(comp)
            fig.add_hline(
                y=per_bucket_target,
                line_dash="dot",
                line_color="gray",
                annotation_text=f"target {per_bucket_target:,.0f}€/bucket",
                annotation_position="top right",
            )
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            comp,
            use_container_width=True,
            hide_index=True,
            column_config={
                "total_value_eur": st.column_config.NumberColumn(
                    "Valore €", format="%.0f"
                ),
                "sovereign_value_eur": st.column_config.NumberColumn(
                    "Sovereign €", format="%.0f"
                ),
                "corporate_value_eur": st.column_config.NumberColumn(
                    "Corporate €", format="%.0f"
                ),
                "weighted_avg_ytm": st.column_config.NumberColumn(
                    "Avg YTM", format="%.2f%%"
                ),
                "current_pct": st.column_config.NumberColumn(
                    "Current %", format="%.1f"
                ),
                "target_pct": st.column_config.NumberColumn(
                    "Target %", format="%.1f"
                ),
            },
        )

    # ----- cash flow projection -----

    st.markdown("---")
    st.subheader("Cash flow previsto (prossimi 24 mesi)")
    st.caption(
        "⚠️ Assunzione semplificata: cedola annuale alla data di scadenza. "
        "Lo schedule reale (frequenza, ex-coupon) richiede un feed dati esterno."
    )

    cf = tracker.get_cash_flow_projection(horizon_weeks=104)
    if cf.empty:
        st.info("Nessun cash flow previsto — aggiungi posizioni per vedere cedole + scadenze.")
    else:
        cf["month"] = pd.to_datetime(cf["date"]).dt.to_period("M").astype(str)
        monthly = cf.groupby(["month", "type"])["amount_eur"].sum().reset_index()
        fig_cf = px.bar(
            monthly,
            x="month",
            y="amount_eur",
            color="type",
            color_discrete_map={"coupon": "#2ca02c", "maturity": "#d62728"},
            title="EUR previsti per mese",
        )
        fig_cf.update_layout(
            template="plotly_white",
            height=320,
            yaxis_title="EUR",
            xaxis_title="Mese",
            margin=dict(l=0, r=0, t=40, b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#888888"),
        )
        st.plotly_chart(fig_cf, use_container_width=True)

        with st.expander(f"Tutti i {len(cf)} eventi di cash flow", expanded=False):
            st.dataframe(cf, use_container_width=True, hide_index=True, height=300)

    # ----- gap analysis -----

    st.markdown("---")
    st.subheader("Gap analysis")

    gaps = tracker.get_gaps()
    if not gaps:
        st.success("✅ Nessun bucket sotto target.")
    else:
        if storage.bonds_db_exists():
            try:
                provider = BorsaItalianaProvider(db_path=storage.bonds_db_path)
                screener_df = provider.list_bonds_df(enrich=True)
            except Exception as e:
                screener_df = pd.DataFrame()
                st.warning(f"Non riesco a leggere lo screener: {e}")
        else:
            screener_df = pd.DataFrame()
            st.info(
                "Bonds DB non trovato — suggerimenti candidati disabilitati. "
                "Esegui `python scripts/migrate_bonds_db.py`."
            )

        for g in gaps[:n_buckets]:
            with st.container(border=True):
                st.markdown(
                    f"**{g['bucket']} bucket** — target {g['target_pct']:.1f}%, "
                    f"current {g['current_pct']:.1f}% → "
                    f"gap **€{g['gap_eur']:,.0f}**"
                )
                if screener_df is not None and not screener_df.empty:
                    g1, g2, g3 = st.columns([1, 1, 1])
                    with g1:
                        max_yield = st.number_input(
                            "Max net yield %",
                            value=15.0,
                            key=f"my_{g['bucket']}",
                            step=0.5,
                        )
                    with g2:
                        currency = st.selectbox(
                            "Currency",
                            ["EUR", "USD", "GBP"],
                            index=0,
                            key=f"cur_{g['bucket']}",
                        )
                    with g3:
                        show_btn = st.button(
                            "Mostra candidati", key=f"show_{g['bucket']}"
                        )
                    if show_btn:
                        filt = screener_df[
                            screener_df["net_yield_pa"].fillna(0) <= max_yield
                        ]
                        candidates = tracker.suggest_candidates_for_bucket(
                            g["bucket"], filt, n_suggestions=10, currency=currency
                        )
                        if candidates.empty:
                            st.warning("Nessun candidato compatibile.")
                        else:
                            cand_cols = [
                                c
                                for c in [
                                    "isin",
                                    "name",
                                    "issuer_type",
                                    "currency",
                                    "coupon",
                                    "net_yield_pa",
                                    "years_to_maturity",
                                    "latest_price",
                                    "maturity_date",
                                ]
                                if c in candidates.columns
                            ]
                            st.dataframe(
                                candidates[cand_cols],
                                use_container_width=True,
                                hide_index=True,
                                height=240,
                            )
                            st.caption(
                                "Usa il form *Aggiungi posizione* qui sotto, oppure "
                                "passa al tab **🏗️ Builder** per generare una proposta completa."
                            )

    # ----- position manager -----

    st.markdown("---")
    st.subheader("Position manager")

    with st.expander("➕ Aggiungi posizione", expanded=active.empty):
        ac1, ac2, ac3 = st.columns(3)
        with ac1:
            new_isin = st.text_input("ISIN", value="", key="add_isin").strip()
            new_desc = st.text_input("Descrizione", value="", key="add_desc")
            new_qty = st.number_input(
                "Valore nominale €", value=10000, step=1000, key="add_qty"
            )
        with ac2:
            new_pp = st.number_input(
                "Prezzo medio acquisto (% face)",
                value=100.0,
                step=0.1,
                key="add_pp",
            )
            new_pdate = st.date_input(
                "Data acquisto", value=date.today(), key="add_pdate"
            )
            new_ytm = st.number_input(
                "YTM al momento dell'acquisto (%)",
                value=3.0,
                step=0.1,
                key="add_ytm",
            )
        with ac3:
            new_coupon = st.number_input(
                "Cedola (%/anno)", value=3.0, step=0.1, key="add_coupon"
            )
            new_mdate = st.date_input(
                "Scadenza",
                value=date(date.today().year + 5, 1, 15),
                key="add_mdate",
            )
            new_itype = st.selectbox(
                "Issuer type",
                ["Government", "Corporate"],
                index=0,
                key="add_itype",
            )
        ac4, ac5, ac6 = st.columns(3)
        with ac4:
            new_nation = st.text_input("Nation", value="Italia", key="add_nation")
        with ac5:
            new_rating = st.text_input(
                "Rating (corporate)", value="", key="add_rating"
            )
        with ac6:
            new_notes = st.text_input("Note", value="", key="add_notes")
        if st.button("Aggiungi posizione", type="primary", key="add_btn"):
            if not new_isin:
                st.error("ISIN obbligatorio.")
            else:
                try:
                    tracker.add_position(
                        isin=new_isin,
                        description=new_desc,
                        quantity=int(new_qty),
                        avg_purchase_price=float(new_pp),
                        purchase_date=new_pdate,
                        ytm_at_purchase=float(new_ytm),
                        coupon=float(new_coupon),
                        maturity_date=new_mdate,
                        nation=new_nation or None,
                        issuer_type=new_itype,
                        rating=new_rating or None,
                        notes=new_notes or "",
                    )
                    st.success(f"Aggiunto {new_isin}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore: {e}")

    if not active.empty:
        edit_cols = [
            c
            for c in [
                "isin",
                "description",
                "quantity",
                "avg_purchase_price",
                "current_price",
                "current_market_value_eur",
                "ytm_current",
                "years_to_maturity",
                "maturity_date",
                "nation",
                "issuer_type",
                "rating",
                "status",
            ]
            if c in active.columns
        ]
        st.dataframe(
            active[edit_cols],
            use_container_width=True,
            hide_index=True,
            height=300,
        )

        with st.expander("✏️ Modifica / chiudi posizione", expanded=False):
            isins = active["isin"].tolist()
            pick = st.selectbox("Pick ISIN", isins, key="edit_pick")
            row = active[active["isin"] == pick].iloc[0] if pick else None
            if row is not None:
                u1, u2, u3 = st.columns(3)
                with u1:
                    upd_qty = st.number_input(
                        "Quantità", value=int(row["quantity"]), step=1000, key="upd_qty"
                    )
                with u2:
                    upd_price = st.number_input(
                        "Prezzo attuale (% face)",
                        value=float(row["current_price"] or 100.0),
                        step=0.1,
                        key="upd_price",
                    )
                with u3:
                    upd_ytm = st.number_input(
                        "YTM attuale (%)",
                        value=float(
                            row["ytm_current"] or row["ytm_at_purchase"] or 0.0
                        ),
                        step=0.1,
                        key="upd_ytm",
                    )
                ub1, ub2, ub3 = st.columns([1, 1, 2])
                with ub1:
                    if st.button("Aggiorna", key="upd_btn"):
                        tracker.update_position(
                            pick,
                            quantity=upd_qty,
                            current_price=upd_price,
                            ytm_current=upd_ytm,
                        )
                        st.success("Aggiornato.")
                        st.rerun()
                with ub2:
                    if st.button("Segna scaduta", key="mat_btn", type="secondary"):
                        tracker.close_position(
                            pick, reason="matured", closed_price=upd_price
                        )
                        st.success("Segnata scaduta.")
                        st.rerun()
                with ub3:
                    if st.button("Segna venduta", key="sold_btn", type="secondary"):
                        tracker.close_position(
                            pick, reason="sold", closed_price=upd_price
                        )
                        st.success("Segnata venduta.")
                        st.rerun()

    # ----- health check -----

    st.markdown("---")
    st.subheader("Health check")
    h = tracker.health_check()
    hc1, hc2, hc3, hc4 = st.columns(4)
    hc1.metric("Health score", f"{h['score']:.0f}/100")
    hc2.metric("Sovereign %", f"{h['metrics']['sovereign_pct']:.1f}%")
    hc3.metric("Avg YTM", f"{h['metrics']['weighted_avg_ytm']:.2f}%")
    hc4.metric("Avg duration", f"{h['metrics']['weighted_avg_duration']:.1f}y")

    if h["warnings"]:
        for w in h["warnings"]:
            if w["level"] == "warning":
                st.warning(w["message"])
            else:
                st.info(w["message"])
    else:
        st.success("Nessun warning.")


# ================================================================
#  TAB 2 — BUILDER (generate proposal from parameters)
# ================================================================

with tab_builder:
    st.markdown(
        "**Cos'è una scala obbligazionaria?** Distribuisce il capitale su scadenze "
        "diverse, così ricevi i soldi a intervalli regolari invece di tutto in una "
        "volta sola. Ogni anno (più o meno) ne scade uno, e i soldi rimborsati "
        "possono essere reinvestiti in un nuovo bond a scadenza lunga — la scala "
        "si rinnova continuamente."
    )
    st.caption(
        "Questa tab **non esegue ordini**. Genera una proposta di acquisto da "
        "copiare manualmente nel broker, poi registra i prezzi effettivi nel Ladder Tracker."
    )

    # ----- parametri -----

    st.subheader("Parametri")
    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        budget = st.number_input(
            "Budget totale (€)",
            min_value=10_000,
            max_value=10_000_000,
            value=50_000,
            step=5_000,
            key="lb_budget",
            help="Capitale totale da allocare nella scala.",
        )
    with bc2:
        n_rungs_b = st.number_input(
            "Numero di gradini",
            min_value=3,
            max_value=20,
            value=10,
            step=1,
            key="lb_n_rungs",
            help="Quante scadenze nella scala (più alto = più granulare, più costi).",
        )
    with bc3:
        max_duration = st.number_input(
            "Duration massima (anni)",
            min_value=2,
            max_value=30,
            value=10,
            step=1,
            key="lb_max_dur",
            help="Scadenza del bond più lungo.",
        )

    with st.expander("⚙️ Impostazioni avanzate", expanded=False):
        ea, eb = st.columns(2)
        with ea:
            tolerance_months = st.slider(
                "Tolerance maturity (mesi)", 1, 12, 6, key="lb_tol"
            )
            gov_ita_w = st.slider("% BTP italiani", 0, 100, 50, key="lb_gi") / 100
            corp_w = (
                st.slider("% obbligazioni aziendali", 0, 100, 25, key="lb_co") / 100
            )
            gov_foreign_w = (
                st.slider("% titoli di stato esteri", 0, 100, 25, key="lb_gf") / 100
            )
        with eb:
            foreign_rating = st.selectbox(
                "Rating minimo gov estero",
                ["AAA", "AA", "A+", "A", "A-"],
                index=4,
                key="lb_fr",
            )
            corp_rating = st.selectbox(
                "Rating minimo aziendale",
                ["A-", "BBB+", "BBB", "BBB-"],
                index=3,
                key="lb_cr",
            )
            max_concentration = st.slider(
                "Max concentrazione per emittente (%)",
                1.0,
                10.0,
                5.0,
                0.5,
                key="lb_mc",
            )

    sum_w = gov_ita_w + corp_w + gov_foreign_w
    if abs(sum_w - 1.0) > 1e-6:
        st.error(
            f"⚠️ Le percentuali devono sommare al 100% — attuale: {sum_w * 100:.0f}%"
        )
        st.stop()

    # ----- generate -----

    if st.button(
        "🔨 Genera proposta ladder", type="primary", key="lb_generate"
    ):
        with st.spinner("Selezionando bond..."):
            try:
                bcfg = LadderBuilderConfig(
                    budget_eur=float(budget),
                    n_rungs=int(n_rungs_b),
                    max_duration_years=int(max_duration),
                    maturity_tolerance_months=int(tolerance_months),
                    gov_ita_weight=float(gov_ita_w),
                    corp_weight=float(corp_w),
                    gov_foreign_weight=float(gov_foreign_w),
                    foreign_min_rating=foreign_rating,
                    corp_min_rating=corp_rating,
                    corp_max_issuer_concentration_pct=float(max_concentration),
                )
                proposal = LadderBuilder(bcfg).build()
                st.session_state["ladder_proposal"] = proposal
                st.session_state.pop("confirming_ladder", None)
                st.success("✅ Proposta generata")
            except Exception as e:
                st.error(f"Errore: {e}")
                st.exception(e)

    proposal = st.session_state.get("ladder_proposal")
    if proposal is None:
        st.info(
            "Imposta i parametri qui sopra e clicca **Genera proposta ladder** "
            "per costruire la scala."
        )
        st.stop()

    # ----- KPI cards -----

    st.markdown("---")
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.metric(
            "Capitale impiegato",
            f"€{proposal.total_allocated_eur:,.0f}",
            delta=f"di €{proposal.total_target_eur:,.0f} previsti",
            delta_color="off",
        )
    with k2:
        st.metric(
            "Rendimento medio annuo",
            f"{proposal.weighted_avg_ytm * 100:.2f}%",
            help="Rendimento netto medio del capitale, ponderato per amount.",
        )
    with k3:
        next_12m = compute_next_12m_cashflow(proposal)
        st.metric(
            "Cash prossimi 12 mesi",
            f"€{next_12m:,.0f}",
            help="Cedole + eventuali rimborsi previsti nei prossimi 12 mesi.",
        )
    with k4:
        st.metric(
            "Numero di bond",
            f"{proposal.n_bonds_selected}",
            delta=(
                f"{proposal.n_bonds_skipped} scartati"
                if proposal.n_bonds_skipped > 0
                else None
            ),
            delta_color="off",
        )

    if proposal.total_unallocated_eur > proposal.total_target_eur * 0.05:
        st.warning(
            f"💡 **€{proposal.total_unallocated_eur:,.0f} non allocati** "
            f"({proposal.total_unallocated_eur / proposal.total_target_eur * 100:.1f}% del budget). "
            f"Tipicamente dovuti a vincoli di lotto minimo (€1000 nominali per bond). "
            f"Considera di aumentare il budget o ridurre il numero di gradini."
        )

    adapted_count = sum(1 for r in proposal.rungs if r.composition_was_adapted)
    if adapted_count > 0:
        st.info(
            f"ℹ️ **{adapted_count} gradini su {len(proposal.rungs)}** ribilanciati "
            f"(quota gov estero → BTP) perché nessun titolo di stato estero nella "
            f"finestra di scadenza ha superato i filtri di qualità."
        )

    if proposal.concentration_warnings:
        st.warning(
            "⚠️ **Concentrazioni emittenti oltre il limite:**\n"
            + "\n".join(f"- {w}" for w in proposal.concentration_warnings)
        )

    # ----- charts -----

    st.plotly_chart(build_ladder_chart(proposal), use_container_width=True)
    st.plotly_chart(build_cashflow_timeline(proposal), use_container_width=True)

    # ----- table -----

    st.subheader("✅ Bond selezionati")
    df = proposal.to_dataframe()
    if df.empty:
        st.info("Nessun bond selezionato.")
    else:
        df_display = df.copy()
        df_display["category"] = df_display["category"].map(
            {
                "gov_ita": "🇮🇹 BTP",
                "corp": "🏢 Aziendale",
                "gov_foreign": "🌍 Estero",
            }
        )
        df_display["ytm_net_pct"] = df_display["ytm_net"] * 100
        st.dataframe(
            df_display[
                [
                    "rung",
                    "target_maturity",
                    "category",
                    "isin",
                    "name",
                    "issuer",
                    "quantity",
                    "price",
                    "amount_eur",
                    "ytm_net_pct",
                    "maturity",
                    "rating",
                ]
            ],
            column_config={
                "rung": st.column_config.NumberColumn("Gradino", width="small"),
                "target_maturity": st.column_config.DateColumn(
                    "Scade verso", format="MMM YYYY"
                ),
                "category": st.column_config.TextColumn("Tipo"),
                "isin": st.column_config.TextColumn("ISIN"),
                "name": st.column_config.TextColumn("Bond", width="large"),
                "issuer": st.column_config.TextColumn("Emittente"),
                "quantity": st.column_config.NumberColumn("Lotti", format="%d"),
                "price": st.column_config.NumberColumn("Prezzo", format="%.2f"),
                "amount_eur": st.column_config.NumberColumn(
                    "Capitale €", format="€%.0f"
                ),
                "ytm_net_pct": st.column_config.NumberColumn(
                    "Rende/anno", format="%.2f%%"
                ),
                "maturity": st.column_config.DateColumn(
                    "Scadenza", format="DD MMM YYYY"
                ),
                "rating": st.column_config.TextColumn("Rating"),
            },
            use_container_width=True,
            hide_index=True,
        )

    # ----- skipped -----

    if proposal.n_bonds_skipped > 0:
        with st.expander(
            f"📋 {proposal.n_bonds_skipped} bond non inclusi (clicca per dettagli)"
        ):
            st.caption(
                "Questi bond sarebbero stati candidati ma sono stati esclusi. "
                "Trasparenza completa."
            )
            reason_translations = {
                "lot_size_exceeds_budget": "Lotto minimo troppo alto per il gradino",
                "concentration_limit": "Già troppo capitale su quell'emittente",
                "corp_rating_too_low": "Rating sotto la soglia minima",
                "foreign_rating_too_low": "Rating estero sotto la soglia minima",
                "foreign_yield_below_btp": "Rende meno del BTP equivalente",
                "foreign_low_liquidity": "Poco scambiato (rischio liquidità)",
                "no_eligible_foreign": "Nessun gov estero idoneo in finestra",
            }
            rows: list[dict] = []
            for r in proposal.rungs:
                for sk in r.skipped_bonds:
                    rows.append(
                        {
                            "Gradino": r.rung_index + 1,
                            "Bond": sk.name,
                            "ISIN": sk.isin,
                            "Tipo": {
                                "gov_ita": "🇮🇹 BTP",
                                "corp": "🏢 Aziendale",
                                "gov_foreign": "🌍 Estero",
                            }.get(sk.category, sk.category),
                            "Motivo": reason_translations.get(sk.reason, sk.reason),
                            "Dettagli": sk.details,
                        }
                    )
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ----- summary -----

    with st.expander("📝 Riassunto a parole", expanded=False):
        c = proposal.actual_composition
        st.markdown(
            f"""
Hai una scala obbligazionaria composta da **{proposal.n_bonds_selected} bond**
suddivisi in **{len(proposal.rungs)} gradini** che coprono i prossimi
**{proposal.config.max_duration_years} anni**.

Ogni anno (o quasi) ne scade uno, restituendoti il capitale che potrai
poi reinvestire in un nuovo bond a scadenza lunga, mantenendo la scala viva.

Nel frattempo, le cedole maturate ti pagano un **rendimento medio annuo del
{proposal.weighted_avg_ytm * 100:.2f}%** sul capitale impiegato
(€{proposal.total_allocated_eur:,.0f} totali su €{proposal.total_target_eur:,.0f}
di budget).

Nei prossimi 12 mesi, ti aspetti di ricevere circa
**€{compute_next_12m_cashflow(proposal):,.0f}** di cash tra cedole e rimborsi
a scadenza.

La composizione complessiva è:
- **{c['gov_ita'] * 100:.0f}% BTP italiani** (la parte più sicura, garantita dallo stato)
- **{c['corp'] * 100:.0f}% obbligazioni aziendali** (aziende solide, leggermente più rendimento ma con rischio credito)
- **{c['gov_foreign'] * 100:.0f}% titoli di stato esteri** (diversificazione geografica, sempre in euro)
"""
        )

    # ----- actions -----

    st.markdown("---")
    st.subheader("🎯 Azioni")
    a1, a2, a3 = st.columns(3)
    with a1:
        csv = df.to_csv(index=False) if not df.empty else ""
        st.download_button(
            "📥 Esporta CSV",
            data=csv,
            file_name=f"ladder_proposal_{date.today().isoformat()}.csv",
            mime="text/csv",
            use_container_width=True,
            disabled=df.empty,
        )
    with a2:
        if st.button(
            "📋 Lista per broker",
            use_container_width=True,
            disabled=df.empty,
            key="lb_broker_btn",
        ):
            st.session_state["show_broker_list"] = True
    with a3:
        if st.button(
            "✅ Conferma posizioni acquisite",
            type="primary",
            use_container_width=True,
            disabled=df.empty,
            key="lb_confirm_btn",
        ):
            st.session_state["confirming_ladder"] = True

    if st.session_state.get("show_broker_list"):
        st.code(format_broker_list(proposal), language="text")

    # ----- confirmation workflow -----

    if st.session_state.get("confirming_ladder"):
        st.markdown("---")
        st.subheader("Conferma prezzi reali di esecuzione")
        st.caption(
            "Inserisci i prezzi effettivi ottenuti dal broker. Al submit, ogni "
            "bond viene registrato nel Ladder Tracker e diventa una posizione live "
            "(visibile nel tab Tracker)."
        )

        flat: list[tuple] = []
        for r in proposal.rungs:
            for category, bond in r.selected_bonds.items():
                if bond is not None:
                    flat.append((r, category, bond))

        with st.form("confirm_form"):
            confirmations: dict[str, dict] = {}
            for r, _category, bond in flat:
                f1, f2, f3 = st.columns([3, 1, 1])
                with f1:
                    st.text(f"Gradino {r.rung_index + 1} — {bond.name} ({bond.isin})")
                with f2:
                    confirmations[bond.isin] = {
                        "price": st.number_input(
                            f"Prezzo effettivo — {bond.isin}",
                            value=float(bond.price_clean),
                            step=0.01,
                            format="%.2f",
                            key=f"px_{bond.isin}",
                            label_visibility="collapsed",
                        ),
                        "bond": bond,
                    }
                with f3:
                    st.text(f"Lotti: {bond.quantity}")

            submitted = st.form_submit_button(
                "💾 Salva nel Ladder Tracker", type="primary"
            )
            if submitted:
                lt = LadderTracker()
                today_dt = date.today()
                ok_, fail_ = [], []
                for isin, payload in confirmations.items():
                    bond = payload["bond"]
                    try:
                        lt.add_position(
                            isin=bond.isin,
                            description=bond.name,
                            quantity=int(bond.quantity * bond.lot_size_eur),
                            avg_purchase_price=float(payload["price"]),
                            purchase_date=today_dt,
                            coupon=float(bond.coupon_rate * 100),
                            maturity_date=bond.maturity_date.date(),
                            ytm_at_purchase=float(bond.ytm_net * 100),
                            nation=bond.country,
                            issuer_type=(
                                "Government" if bond.category != "corp" else "Corporate"
                            ),
                            rating=bond.rating,
                            notes=(
                                f"Generato da Ladder Builder — gradino target "
                                f"{bond.maturity_date.strftime('%Y-%m')}"
                            ),
                            current_price=float(payload["price"]),
                        )
                        ok_.append(bond.isin)
                    except Exception as e:
                        fail_.append((bond.isin, str(e)))
                if ok_:
                    st.success(
                        f"✅ Registrate **{len(ok_)} posizioni** nel Ladder Tracker. "
                        f"Passa al tab **📊 Tracker** per vederle."
                    )
                if fail_:
                    st.error(
                        "Alcune posizioni non sono state registrate:\n"
                        + "\n".join(f"- `{isin}`: {err}" for isin, err in fail_)
                    )
                st.session_state.pop("confirming_ladder", None)
