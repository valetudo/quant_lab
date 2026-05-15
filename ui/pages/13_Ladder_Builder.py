"""Ladder Builder — generatore di proposte di acquisto bond (v3.1.0).

Pagina dedicata estratta dal vecchio tab 2 di ``4_Bonds_Ladder.py``
(archiviata in v3.1.0). Contenuto identico: parametri form, generazione
proposta, KPI cards, ladder chart (scala letterale), cash-flow timeline,
tabella, skipped bonds, summary, azioni + workflow conferma.
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
    ParamCandidate,
    compute_next_12m_cashflow,
    find_optimal_params,
)
from ui.components.mode_badge import mode_badge
from ui.utils.ladder_viz import build_cashflow_timeline, build_ladder_chart

# ----- pending widget updates (must run BEFORE any widget is rendered) -----
#
# Streamlit forbids writing to ``st.session_state[KEY]`` once a widget with
# ``key=KEY`` has been instantiated in the current run — it raises
# ``StreamlitAPIException``. The "Usa questi" button on the optimal-params
# panel (added in v3.1.2) wanted to push new values into the form widgets,
# so it crashed.
#
# Pattern: the button stages its updates into the special
# ``_pending_lb_apply`` dict and reruns; we apply them HERE, at the top of
# the script, before any widget exists, then pop the staging key so the
# update fires exactly once.
_pending = st.session_state.pop("_pending_lb_apply", None)
if _pending:
    for _k, _v in _pending.items():
        st.session_state[_k] = _v

st.set_page_config(page_title="Ladder Builder", page_icon="🏗️", layout="wide")
st.title("🏗️ Ladder Builder")
mode_badge(
    "ricerca",
    "Genera una proposta di bond ladder strutturata da budget + parametri. "
    "Selezione dal catalogo Borsa Italiana con composizione target + filtri "
    "qualitativi.",
)

st.markdown(
    "**Cos'è una scala obbligazionaria?** Distribuisce il capitale su scadenze "
    "diverse, così ricevi i soldi a intervalli regolari invece di tutto in una "
    "volta sola. Ogni anno (più o meno) ne scade uno, e i soldi rimborsati "
    "possono essere reinvestiti in un nuovo bond a scadenza lunga — la scala "
    "si rinnova continuamente."
)
st.caption(
    "Questa pagina **non esegue ordini**. Genera una proposta di acquisto da "
    "copiare manualmente nel broker, poi registra i prezzi effettivi nel "
    "Ladder Tracker."
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

    st.markdown("---")
    st.markdown("**Strategia di allocazione**")
    maximize_allocation = st.checkbox(
        "🎯 Massimizza allocazione",
        value=False,
        key="lb_maximize",
        help=(
            "Quando attivo, il builder cerca di allocare il 100 % del budget "
            "anche se questo significa:\n"
            "- Espandere la tolerance window di scadenza (es. ±12 mesi invece di ±6, "
            "fino a ±24 mesi)\n"
            "- Ridistribuire l'eventuale residuo non allocato sui gradini con più "
            "capacity\n\n"
            "Trade-off: leggera variazione del rendimento medio "
            "(tipicamente ±0.1–0.3 pp), in cambio di allocazione completa.\n\n"
            "Default OFF: comportamento standard, può lasciare residuo se i "
            "vincoli sono stretti."
        ),
    )

sum_w = gov_ita_w + corp_w + gov_foreign_w
if abs(sum_w - 1.0) > 1e-6:
    st.error(
        f"⚠️ Le percentuali devono sommare al 100% — attuale: {sum_w * 100:.0f}%"
    )
    st.stop()


# ----- optimal-params finder -----

# Build a config snapshot from the current advanced settings so the finder
# inherits user tweaks (composition weights, rating gates, etc.).
def _current_base_config() -> LadderBuilderConfig:
    return LadderBuilderConfig(
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


finder_c1, finder_c2 = st.columns([1, 4])
with finder_c1:
    if st.button(
        "🔍 Trova parametri ottimali",
        key="lb_find_optimal",
        help=(
            "Scansiona ~30 combinazioni di (numero gradini, duration massima) "
            "per il budget corrente e ti suggerisce le migliori per allocazione "
            "totale. Tipicamente < 2 s. Non cambia subito i parametri — ti "
            "mostra le opzioni, scegli tu."
        ),
    ):
        with st.spinner("Esplorando combinazioni…"):
            try:
                st.session_state["lb_optimal_results"] = find_optimal_params(
                    budget_eur=float(budget),
                    base_config=_current_base_config(),
                    top_n=5,
                )
            except Exception as e:
                st.error(f"Errore nella scansione: {e}")

with finder_c2:
    st.caption(
        "💡 *Suggerimento*: budget piccoli con duration alta lasciano spesso "
        "molti gradini sotto-allocati. Clicca «Trova parametri ottimali» per "
        "vedere automaticamente le combinazioni con miglior coverage."
    )

_optimal_results: list[ParamCandidate] = st.session_state.get(
    "lb_optimal_results", []
)
if _optimal_results:
    with st.container(border=True):
        best = _optimal_results[0]
        below_80 = best.coverage_pct < 80.0
        if below_80:
            st.warning(
                f"⚠️ Per €{budget:,.0f} di budget nessuna combinazione "
                f"raggiunge l'80% di coverage senza maximize_allocation. "
                f"Migliore: **{best.coverage_pct:.1f}%**. Considera di "
                f"aumentare il budget oppure attivare il toggle "
                f"**🎯 Massimizza allocazione**."
            )
        else:
            st.success(
                f"✅ Trovate {len(_optimal_results)} combinazioni con "
                f"coverage ≥ 80% per €{budget:,.0f}."
            )

        for idx, cand in enumerate(_optimal_results):
            cols = st.columns([3, 1, 1, 1, 1])
            badge = "🏆" if idx == 0 else f"#{idx + 1}"
            with cols[0]:
                st.markdown(
                    f"**{badge}** · {cand.n_rungs} gradini · "
                    f"max duration {cand.max_duration_years}y · "
                    f"{cand.n_bonds_selected} bond"
                )
            cols[1].metric(
                "Coverage",
                f"{cand.coverage_pct:.1f}%",
                delta=None,
                delta_color="off",
            )
            cols[2].metric(
                "YTM medio",
                f"{cand.weighted_avg_ytm * 100:.2f}%",
                delta=None,
                delta_color="off",
            )
            cols[3].metric(
                "Allocato",
                f"€{cand.allocated_eur:,.0f}",
                delta=None,
                delta_color="off",
            )
            with cols[4]:
                if st.button(
                    "Usa questi",
                    key=f"lb_apply_opt_{idx}",
                    type=("primary" if idx == 0 else "secondary"),
                ):
                    # Stage the widget-keyed updates instead of writing
                    # straight to session_state — direct writes would fail
                    # because the number_input widgets have already been
                    # instantiated higher up in this script run.
                    # The staging dict is consumed at the top of the next
                    # run, before any widget renders.
                    st.session_state["_pending_lb_apply"] = {
                        "lb_n_rungs": cand.n_rungs,
                        "lb_max_dur": cand.max_duration_years,
                    }
                    # Promote the pre-computed proposal to the live
                    # proposal so the ladder renders immediately — no need
                    # for the user to click "Genera proposta" again.
                    # The finder already built it (standard pass), so this
                    # is zero extra compute.
                    if cand.proposal is not None:
                        st.session_state["ladder_proposal"] = cand.proposal
                        st.session_state.pop("confirming_ladder", None)
                        st.session_state.pop("show_broker_list", None)
                    # Keep the recommendation panel visible so the user can
                    # click another "Usa questi" and flip instantly.
                    st.rerun()


# ----- generate -----

if st.button("🔨 Genera proposta ladder", type="primary", key="lb_generate"):
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
                maximize_allocation=bool(maximize_allocation),
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
    _SOFT_LIMIT_PCT = proposal.config.corp_max_issuer_concentration_pct

    def _parse_excess(w: str) -> tuple[str, float]:
        """Extract (issuer, pct) from 'Obligaciones Fx: 5.3% > limite 5%'."""
        try:
            issuer = w.split(":", 1)[0].strip()
            pct = float(w.split(":", 1)[1].split("%", 1)[0].strip())
            return issuer, pct
        except (IndexError, ValueError):
            return w, _SOFT_LIMIT_PCT

    parsed = [_parse_excess(w) for w in proposal.concentration_warnings]
    max_excess_pp = max((p - _SOFT_LIMIT_PCT for _, p in parsed), default=0.0)

    with st.container(border=True):
        hcol1, hcol2 = st.columns([10, 1])
        with hcol1:
            st.markdown(
                "### ⚠️ Concentrazione singolo emittente sopra raccomandazione"
            )
        with hcol2:
            st.markdown(
                "ℹ️",
                help=(
                    "Per diversificazione del rischio credito, si raccomanda di "
                    f"non superare il {_SOFT_LIMIT_PCT:.0f}% del budget per singolo "
                    "emittente corporate.\n\n"
                    "Se un emittente fallisce, perdere il 5% del portfolio è "
                    "doloroso ma gestibile; perdere il 15% è catastrofico.\n\n"
                    "Sforamenti minimi (< 2 pp) sono accettabili. Sforamenti "
                    "significativi richiedono di ridurre la posizione "
                    "manualmente o aumentare budget/gradini."
                ),
            )
        st.markdown(
            "Per diversificazione del rischio credito, si raccomanda di non "
            f"superare il **{_SOFT_LIMIT_PCT:.0f}%** del budget per singolo "
            "emittente corporate. Nella tua ladder:"
        )
        for issuer, pct in parsed:
            excess = pct - _SOFT_LIMIT_PCT
            severity = "minimo" if excess < 2.0 else "significativo"
            st.markdown(
                f"- **{issuer}**: {pct:.1f}% del capitale allocato "
                f"(raccomandato: max {_SOFT_LIMIT_PCT:.0f}%, sforamento {severity})"
            )
        if max_excess_pp < 2.0:
            st.info(
                "ℹ️ Questi sforamenti sono minimi e accettabili. Per essere più "
                "stretto, riduci il budget per il singolo emittente o aumenta il "
                "numero di gradini per diluire la posizione."
            )
        else:
            st.warning(
                "⚠️ Sforamenti significativi. Considera di ribilanciare "
                "manualmente vendendo parte delle posizioni concentrate, oppure "
                "rigenera la proposta con vincoli più stretti (più gradini, "
                "budget più alto)."
            )

# ----- maximize-allocation info banner -----

if proposal.config.maximize_allocation:
    yield_now = proposal.weighted_avg_ytm
    yield_before = proposal.yield_without_maximization
    alloc_pct = (
        proposal.total_allocated_eur / proposal.total_target_eur * 100
        if proposal.total_target_eur > 0
        else 0
    )
    if yield_before is not None and abs(yield_now - yield_before) > 1e-6:
        diff_pp = (yield_now - yield_before) * 100
        st.info(
            f"📊 **Massimizzazione allocazione attiva** — rendimento medio "
            f"**{yield_now * 100:.2f}%** (senza massimizzazione: "
            f"{yield_before * 100:.2f}%, impatto {diff_pp:+.2f} pp). "
            f"Allocato €{proposal.total_allocated_eur:,.0f} di "
            f"€{proposal.total_target_eur:,.0f} ({alloc_pct:.1f} %)."
        )
    else:
        st.info(
            f"📊 **Massimizzazione allocazione attiva** — non sono stati "
            f"trovati bond aggiuntivi per i gradini sotto-allocati. "
            f"Allocato €{proposal.total_allocated_eur:,.0f} di "
            f"€{proposal.total_target_eur:,.0f} ({alloc_pct:.1f} %)."
        )

# ----- allocation log -----

if proposal.allocation_log:
    with st.expander(
        "📋 Log dettagliato del processo di allocazione", expanded=False
    ):
        st.caption(
            "Traccia step-by-step di come il builder ha allocato il budget. "
            "Utile per capire perché certi gradini sono sotto-allocati o "
            "perché certi bond sono stati scartati."
        )
        for entry in proposal.allocation_log:
            if entry.startswith("Step"):
                st.markdown(f"**{entry}**")
            else:
                st.markdown(entry)

# ----- charts -----

st.plotly_chart(build_ladder_chart(proposal), use_container_width=True)
st.plotly_chart(build_cashflow_timeline(proposal), use_container_width=True)


# ----- Borsa Italiana link table -----


def _borsa_italiana_url(isin: str, bond_name: str = "") -> str:
    """Build the Borsa Italiana scheda URL for a bond.

    Verified pattern (v3.1.5):
        /borsa/obbligazioni/mot/<categoria>/scheda/<ISIN>.html?lang=it

    ``<categoria>`` is inferred from the instrument name:
      - Italian sovereigns (BTP / BOT / CCT / CTZ) → ``btp``
      - everything else (foreign sovereigns + corporates) →
        ``obbligazioni-euro``

    The old v3.1.1 endpoint ``cerca-titolo.html?search=`` returned 404 —
    it never existed. For bonds whose category can't be guessed
    reliably, :func:`_borsa_italiana_fallback_url` gives a web-search
    link that always resolves.
    """
    isin = (isin or "").upper().strip()
    name_upper = (bond_name or "").upper()
    italian_sov = ("BTP", "BOT", "CCT", "CTZ")
    if any(tok in name_upper for tok in italian_sov):
        categoria = "btp"
    else:
        categoria = "obbligazioni-euro"
    return (
        f"https://www.borsaitaliana.it/borsa/obbligazioni/mot/"
        f"{categoria}/scheda/{isin}.html?lang=it"
    )


def _borsa_italiana_fallback_url(isin: str) -> str:
    """Web-search fallback — always resolves.

    Used as the second link column for bonds whose BI sub-category can't
    be inferred from the name (e.g. some corporates). A Google search
    scoped to ``site:borsaitaliana.it`` lands on the right scheda.
    """
    isin = (isin or "").upper().strip()
    return f"https://www.google.com/search?q=site%3Aborsaitaliana.it+{isin}"


st.subheader("🔗 Apri scheda Borsa Italiana")
st.caption(
    "Click su **🔗 Scheda** per la pagina ufficiale Borsa Italiana del bond "
    "(prezzi, prospetto, dati storici). Se il link non funziona "
    "(categorizzazione errata per alcuni corporate), usa **🔍 Cerca** per "
    "trovare la scheda tramite ricerca web."
)

_link_rows: list[dict] = []
for _rung in proposal.rungs:
    for _category, _bond in _rung.selected_bonds.items():
        if _bond is None:
            continue
        _emoji = {"gov_ita": "🇮🇹", "corp": "🏢", "gov_foreign": "🌍"}.get(
            _category, "•"
        )
        _link_rows.append(
            {
                "Gradino": _rung.rung_index + 1,
                "Tipo": _emoji,
                "Bond": _bond.name,
                "ISIN": _bond.isin,
                "Capitale €": _bond.amount_eur,
                "YTM %": _bond.ytm_net * 100,
                "🔗 Scheda": _borsa_italiana_url(_bond.isin, _bond.name),
                "🔍 Cerca": _borsa_italiana_fallback_url(_bond.isin),
            }
        )

if _link_rows:
    st.dataframe(
        pd.DataFrame(_link_rows),
        column_config={
            "Gradino": st.column_config.NumberColumn(
                "Gradino", width="small", format="%d"
            ),
            "Tipo": st.column_config.TextColumn("Tipo", width="small"),
            "Bond": st.column_config.TextColumn("Nome", width="large"),
            "ISIN": st.column_config.TextColumn("ISIN", width="medium"),
            "Capitale €": st.column_config.NumberColumn(
                "Capitale", format="€%.0f"
            ),
            "YTM %": st.column_config.NumberColumn("YTM", format="%.2f%%"),
            "🔗 Scheda": st.column_config.LinkColumn(
                "🔗 Scheda",
                display_text="Apri",
            ),
            "🔍 Cerca": st.column_config.LinkColumn(
                "🔍 Cerca",
                display_text="Search",
            ),
        },
        hide_index=True,
        use_container_width=True,
    )


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
st.subheader("📤 Esporta proposta")

# Build the PDF once per render so the download is a single click.
_pdf_bytes: bytes | None = None
if not df.empty:
    try:
        from io import BytesIO

        from reporting.ladder_pdf import generate_ladder_pdf

        _pdf_buf = BytesIO()
        generate_ladder_pdf(
            proposal,
            _pdf_buf,
            build_borsa_url_fn=_borsa_italiana_url,
        )
        _pdf_bytes = _pdf_buf.getvalue()
    except Exception as e:  # pragma: no cover - defensive
        st.caption(f"⚠️ PDF non disponibile: {e}")

e1, e2 = st.columns(2)
with e1:
    csv = df.to_csv(index=False) if not df.empty else ""
    st.download_button(
        "📥 Esporta CSV",
        data=csv,
        file_name=f"bond_ladder_{date.today().isoformat()}.csv",
        mime="text/csv",
        use_container_width=True,
        disabled=df.empty,
    )
with e2:
    st.download_button(
        "📄 Esporta PDF",
        data=_pdf_bytes if _pdf_bytes is not None else b"",
        file_name=f"bond_ladder_{date.today().isoformat()}.pdf",
        mime="application/pdf",
        use_container_width=True,
        disabled=_pdf_bytes is None,
        help=(
            "PDF formattato: cover + grafico ladder + tabella bond con "
            "link cliccabili a Borsa Italiana + note operative."
        ),
    )
