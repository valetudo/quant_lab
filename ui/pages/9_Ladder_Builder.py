"""Bond Ladder Builder — input parameters → concrete purchase proposal.

Storytelling-first UI: form, KPI cards in plain Italian, the "literal
ladder" chart, the cash-flow timeline, a transparent skipped-bonds
table, and a confirmation workflow that writes the executed positions
into the existing :class:`LadderTracker`.

This is a pure decision-support page. No live orders are placed; the user
copies the broker list into their broker and confirms the actual executed
prices afterward.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

# --- bootstrap ---
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# ---

from strategies.bonds_income.ladder_builder import (
    LadderBuilder,
    LadderBuilderConfig,
    compute_next_12m_cashflow,
    format_broker_list,
)
from ui.utils.ladder_viz import build_cashflow_timeline, build_ladder_chart

st.set_page_config(page_title="Ladder Builder", page_icon="🏗️", layout="wide")

# ----- header didattico -----

st.title("🏗️ Bond Ladder Builder")
st.markdown(
    "**Cos'è una scala obbligazionaria?** "
    "Distribuisce il capitale su scadenze diverse, così ricevi indietro i soldi "
    "a intervalli regolari invece di tutto in una volta sola. Ogni anno (più o meno) "
    "ne scade uno, e i soldi rimborsati possono essere reinvestiti in un nuovo bond "
    "a scadenza lunga — la scala si rinnova continuamente."
)

st.caption(
    "Questa pagina **non esegue ordini**. Genera una proposta di acquisto da "
    "copiare manualmente nel broker, poi registra i prezzi effettivi nel Ladder Tracker."
)


# ----- parametri -----

st.subheader("Parametri")
c1, c2, c3 = st.columns(3)
with c1:
    budget = st.number_input(
        "Budget totale (€)",
        min_value=10_000,
        max_value=10_000_000,
        value=50_000,
        step=5_000,
        help="Capitale totale da allocare nella scala.",
    )
with c2:
    n_rungs = st.number_input(
        "Numero di gradini",
        min_value=3,
        max_value=20,
        value=10,
        step=1,
        help="Quante scadenze nella scala (più alto = più granulare, più costi).",
    )
with c3:
    max_duration = st.number_input(
        "Duration massima (anni)",
        min_value=2,
        max_value=30,
        value=10,
        step=1,
        help="Scadenza del bond più lungo.",
    )

with st.expander("⚙️ Impostazioni avanzate", expanded=False):
    aa, bb = st.columns(2)
    with aa:
        tolerance_months = st.slider("Tolerance maturity (mesi)", 1, 12, 6)
        gov_ita_w = st.slider("% BTP italiani", 0, 100, 50) / 100
        corp_w = st.slider("% obbligazioni aziendali", 0, 100, 25) / 100
        gov_foreign_w = st.slider("% titoli di stato esteri", 0, 100, 25) / 100
    with bb:
        foreign_rating = st.selectbox(
            "Rating minimo gov estero",
            ["AAA", "AA", "A+", "A", "A-"],
            index=4,
        )
        corp_rating = st.selectbox(
            "Rating minimo aziendale",
            ["A-", "BBB+", "BBB", "BBB-"],
            index=3,
        )
        max_concentration = st.slider(
            "Max concentrazione per emittente (%)",
            1.0,
            10.0,
            5.0,
            0.5,
        )

total_w = gov_ita_w + corp_w + gov_foreign_w
if abs(total_w - 1.0) > 1e-6:
    st.error(
        f"⚠️ Le percentuali devono sommare al 100% — attuale: {total_w * 100:.0f}%"
    )
    st.stop()


# ----- generate -----

if st.button("🔨 Genera proposta ladder", type="primary"):
    with st.spinner("Selezionando bond..."):
        try:
            cfg = LadderBuilderConfig(
                budget_eur=float(budget),
                n_rungs=int(n_rungs),
                max_duration_years=int(max_duration),
                maturity_tolerance_months=int(tolerance_months),
                gov_ita_weight=float(gov_ita_w),
                corp_weight=float(corp_w),
                gov_foreign_weight=float(gov_foreign_w),
                foreign_min_rating=foreign_rating,
                corp_min_rating=corp_rating,
                corp_max_issuer_concentration_pct=float(max_concentration),
            )
            proposal = LadderBuilder(cfg).build()
            st.session_state["ladder_proposal"] = proposal
            st.session_state.pop("confirming_ladder", None)
            st.success("✅ Proposta generata")
        except Exception as e:
            st.error(f"Errore: {e}")
            st.exception(e)


# ----- display proposal -----

proposal = st.session_state.get("ladder_proposal")
if proposal is None:
    st.info(
        "Imposta i parametri qui sopra e clicca **Genera proposta ladder** "
        "per costruire la scala."
    )
    st.stop()


# ----- KPI cards in italiano -----

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
        help="Quanto rende in media il capitale ogni anno, al netto delle tasse",
    )
with k3:
    next_12m = compute_next_12m_cashflow(proposal)
    st.metric(
        "Cash prossimi 12 mesi",
        f"€{next_12m:,.0f}",
        help="Cedole + eventuali rimborsi previsti nei prossimi 12 mesi",
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

# Unallocated banner
if proposal.total_unallocated_eur > proposal.total_target_eur * 0.05:
    st.warning(
        f"💡 **€{proposal.total_unallocated_eur:,.0f} non allocati** "
        f"({proposal.total_unallocated_eur / proposal.total_target_eur * 100:.1f}% del budget). "
        f"Tipicamente dovuti a vincoli di lotto minimo (€1000 nominali per bond). "
        f"Considera di aumentare il budget o ridurre il numero di gradini."
    )

# Adapted-rung banner
adapted_count = sum(1 for r in proposal.rungs if r.composition_was_adapted)
if adapted_count > 0:
    st.info(
        f"ℹ️ **{adapted_count} gradini su {len(proposal.rungs)}** sono stati ribilanciati "
        f"(la quota di gov estero è passata a BTP) perché nessun titolo di stato estero "
        f"nella finestra di scadenza ha superato i filtri di qualità."
    )

# Concentration warnings
if proposal.concentration_warnings:
    st.warning(
        "⚠️ **Concentrazioni emittenti oltre il limite:**\n"
        + "\n".join(f"- {w}" for w in proposal.concentration_warnings)
    )


# ----- charts -----

st.plotly_chart(build_ladder_chart(proposal), use_container_width=True)
st.plotly_chart(build_cashflow_timeline(proposal), use_container_width=True)


# ----- selected bonds table -----

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
    # ytm_net is decimal; show as % with proper unit. Streamlit's
    # `format="%.2f%%"` multiplies by 100 by default for `NumberColumn`
    # only when configured as a percentage — easier to pre-format.
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


# ----- skipped bonds expander -----

if proposal.n_bonds_skipped > 0:
    with st.expander(
        f"📋 {proposal.n_bonds_skipped} bond non inclusi (clicca per dettagli)"
    ):
        st.caption(
            "Questi bond sarebbero stati candidati ma sono stati esclusi per "
            "ragioni operative. Trasparenza completa."
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
        skipped_rows: list[dict] = []
        for rung in proposal.rungs:
            for sk in rung.skipped_bonds:
                skipped_rows.append(
                    {
                        "Gradino": rung.rung_index + 1,
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
        st.dataframe(
            pd.DataFrame(skipped_rows),
            use_container_width=True,
            hide_index=True,
        )


# ----- textual summary -----

with st.expander("📝 Riassunto a parole", expanded=False):
    comp = proposal.actual_composition
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
**€{compute_next_12m_cashflow(proposal):,.0f}** di cash tra cedole e
rimborsi a scadenza.

La composizione complessiva è:
- **{comp['gov_ita'] * 100:.0f}% BTP italiani** (la parte più sicura, garantita dallo stato)
- **{comp['corp'] * 100:.0f}% obbligazioni aziendali** (aziende solide, leggermente più rendimento ma con rischio credito)
- **{comp['gov_foreign'] * 100:.0f}% titoli di stato esteri** (diversificazione geografica, sempre in euro)
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
    if st.button("📋 Lista per broker", use_container_width=True, disabled=df.empty):
        st.session_state["show_broker_list"] = True
with a3:
    if st.button(
        "✅ Conferma posizioni acquisite",
        type="primary",
        use_container_width=True,
        disabled=df.empty,
    ):
        st.session_state["confirming_ladder"] = True

if st.session_state.get("show_broker_list"):
    st.code(format_broker_list(proposal), language="text")


# ----- confirmation workflow (Task 5) -----

if st.session_state.get("confirming_ladder"):
    st.markdown("---")
    st.subheader("Conferma prezzi reali di esecuzione")
    st.caption(
        "Inserisci i prezzi effettivi ottenuti dal broker (di solito differiscono "
        "leggermente da quelli proposti). Al submit, ogni bond viene registrato "
        "nel Ladder Tracker e diventa una posizione live."
    )

    flat_bonds: list[tuple] = []
    for rung in proposal.rungs:
        for category, bond in rung.selected_bonds.items():
            if bond is not None:
                flat_bonds.append((rung, category, bond))

    with st.form("confirm_form"):
        confirmations: dict[str, dict] = {}
        for rung, category, bond in flat_bonds:
            c_a, c_b, c_c = st.columns([3, 1, 1])
            with c_a:
                st.text(f"Gradino {rung.rung_index + 1} — {bond.name} ({bond.isin})")
            with c_b:
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
            with c_c:
                st.text(f"Lotti: {bond.quantity}")

        submitted = st.form_submit_button(
            "💾 Salva nel Ladder Tracker", type="primary"
        )

        if submitted:
            from strategies.bonds_income.ladder import LadderTracker

            tracker = LadderTracker()
            today_dt = date.today()
            successes: list[str] = []
            failures: list[tuple[str, str]] = []
            for isin, payload in confirmations.items():
                bond = payload["bond"]
                try:
                    tracker.add_position(
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
                    successes.append(bond.isin)
                except Exception as e:
                    failures.append((bond.isin, str(e)))

            if successes:
                st.success(
                    f"✅ Registrate **{len(successes)} posizioni** nel Ladder Tracker."
                )
            if failures:
                st.error(
                    "Alcune posizioni non sono state registrate:\n"
                    + "\n".join(f"- `{isin}`: {err}" for isin, err in failures)
                )
            st.session_state.pop("confirming_ladder", None)
            st.info(
                "Vai alla pagina **🏗️ Bond Ladder** per vedere e gestire le "
                "posizioni registrate."
            )
