"""Alternative Strategies — opportunistic sleeve management.

Lists strategies registered for the opportunistic sleeve (auto-discovered
via :class:`core.strategy.registry.StrategyRegistry`). For each strategy
shows status, README link, and a button to either backtest it in the lab
or register a position.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import streamlit as st

# --- bootstrap ---
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# ---

from core.strategy.registry import StrategyRegistry
from portfolio.position_tracker import PositionTracker

st.set_page_config(
    page_title="Alternative Strategies", page_icon="🎯", layout="wide"
)
st.title("🎯 Alternative Strategies")
st.caption(
    "Strategie attive per l'opportunistic sleeve. Validale prima di metterci "
    "capitale reale: walk-forward + benchmark vs alternativa passiva."
)

registry = StrategyRegistry()
alt = registry.by_sleeve("opportunistic")

if not alt:
    st.info(
        "Nessuna strategia opportunistic registrata. Per aggiungerne una: "
        "drop `strategies/<id>/strategy.py` + `config.yaml` e riavvia Streamlit. "
        "Vedi `docs/adding_a_strategy.md`."
    )
    st.stop()

STATUS_BADGE = {
    "active": ("🟢", "Attiva"),
    "scaffold": ("🟡", "Scaffold"),
    "deprecated": ("⚫", "Archiviata"),
}

for s in alt:
    with st.container(border=True):
        c1, c2, c3 = st.columns([3, 1, 1])
        icon, label = STATUS_BADGE.get(s.status, ("⚪", s.status))
        with c1:
            st.markdown(f"### {icon} `{s.id}` — {label}")
            if s.description:
                st.caption(s.description)
            st.markdown(f"**Path**: `{s.directory}`")
        with c2:
            st.metric("Status", s.status)
        with c3:
            st.metric("Sleeve", s.sleeve)

        # Status-specific actions
        if s.status == "scaffold":
            st.warning(
                "⚠️ Questa strategia è in stato **scaffold**: il codice è "
                "abbozzato ma non ancora validato. Vedi il README della "
                "strategia per i passi di attivazione."
            )
            if s.readme_path and Path(s.readme_path).exists():
                with st.expander("📖 README"):
                    try:
                        st.markdown(
                            Path(s.readme_path).read_text(encoding="utf-8")
                        )
                    except Exception as e:
                        st.error(f"Non riesco a leggere il README: {e}")

        elif s.status == "active":
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button(
                    "🔬 Apri in Backtest Lab",
                    key=f"bt_{s.id}",
                    use_container_width=True,
                ):
                    st.session_state["lab_strategy"] = s.id
                    st.switch_page("pages/9_Backtest_Lab.py")
            with col_b:
                if st.button(
                    "💼 Registra posizione",
                    key=f"reg_{s.id}",
                    use_container_width=True,
                ):
                    st.session_state["adding_position_strategy"] = s.id

        elif s.status == "deprecated":
            st.info(
                "Questa strategia è stata archiviata. Vedi `_migration_log/` "
                "per la decision history."
            )

        # Position registration form
        if st.session_state.get("adding_position_strategy") == s.id:
            with st.form(f"pos_form_{s.id}"):
                st.markdown(f"**Registra posizione per `{s.id}`**")
                pc1, pc2 = st.columns(2)
                with pc1:
                    amount = st.number_input(
                        "Capitale impiegato (€)",
                        min_value=100.0,
                        step=100.0,
                        value=5_000.0,
                    )
                with pc2:
                    pdate = st.date_input("Data inizio", value=date.today())
                submitted = st.form_submit_button("💾 Registra", type="primary")
                if submitted:
                    tr = PositionTracker()
                    tr.add_alternative(
                        strategy_id=s.id,
                        name=f"{s.id} position",
                        quantity=1,
                        avg_purchase_price=float(amount),
                        purchase_date=pdate,
                    )
                    st.success(
                        f"✅ Posizione `{s.id}` registrata "
                        f"(€{amount:,.0f} dal {pdate.isoformat()})."
                    )
                    st.session_state.pop("adding_position_strategy", None)
                    st.rerun()

st.markdown("---")

with st.expander("➕ Aggiungere una nuova strategia"):
    st.markdown(
        """
Il framework è plug-and-play:

1. Crea `strategies/<nome>/strategy.py` con classe che eredita da `Strategy`.
2. Crea `strategies/<nome>/config.yaml` con `sleeve: opportunistic`.
3. Riavvia Streamlit — la strategia viene auto-rilevata.

Guida completa: `docs/adding_a_strategy.md`.

**Validation checklist** prima di promuovere a `status: active`:
- ✅ Walk-forward 5+ fold con median OOS Sharpe > 0.2
- ✅ Benchmark comparison vs alternativa passiva rilevante
- ✅ Survivorship correction se equity-based
- ✅ Paper trading 3+ mesi prima di deploy

Lezione di Quality Stocks V5 (archiviata): non saltare nessuno di questi passi.
"""
    )
