"""Alternative — modular hub per le strategie attive (v3.0.0).

Auto-discovers le strategie dal registry e le raggruppa per stato:

- 🟢 active     — già deployate con capitale
- 🔵 validated  — pronte per il deploy (walk-forward + benchmark passati)
- 🟡 scaffold   — in sviluppo, non ancora validate
- 🔴 archived   — validation fallita o performance degradata

Click su "Esplora →" apre un dettaglio per strategia con README,
configurazione e link al Backtest Lab (pagina hidden ma URL-reachable).
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

from core.strategy.registry import StrategyRegistry
from ui.components.mode_badge import mode_badge

st.set_page_config(
    page_title="Alternative Strategies", page_icon="🎯", layout="wide"
)

st.title("🎯 Alternative")
mode_badge(
    "ricerca",
    "Hub per strategie alternative attive (short-term, intraday, event-driven). "
    "Include backtest framework e walk-forward validation.",
)

# ----- intro -----

st.markdown(
    """
Questa sezione ospita strategie attive da validare prima di un eventuale deploy
con capitale reale. Ogni strategia **deve** passare:

1. **Walk-forward** con OOS Sharpe stabile (median > 0.5, nessun fold con verdetto negativo).
2. **Benchmark comparison** vs un'alternativa passiva rilevante (deve battere il passive).
3. **Survivorship correction** se equity-based.

> Lezione Quality Stocks V5 (archived): walk-forward passa, ma se benchmark
> fallisce → archive. Non saltare nessuno dei due step.
"""
)

# ----- registry-driven listing -----

registry = StrategyRegistry()
all_strategies = list(registry.all())

# Filter to alternative / opportunistic only. We exclude the bonds + equity
# sleeves: those have dedicated pages.
alt_strategies = [
    s for s in all_strategies if s.sleeve in ("opportunistic", "alternative")
]

# Group by status
_GROUPS_ORDER = ("active", "validated", "scaffold", "archived")
_STATUS_CFG = {
    "active": {"emoji": "🟢", "label": "Attive (in produzione)"},
    "validated": {"emoji": "🔵", "label": "Validate (pronte per deploy)"},
    "scaffold": {"emoji": "🟡", "label": "Scaffold (in sviluppo)"},
    "archived": {"emoji": "🔴", "label": "Archiviate (validation fallita)"},
}

groups: dict[str, list] = {k: [] for k in _GROUPS_ORDER}
for s in alt_strategies:
    groups.setdefault(s.status, []).append(s)

if not alt_strategies:
    st.info(
        "Nessuna strategia opportunistic registrata. Per aggiungerne una: "
        "drop `strategies/<id>/strategy.py` + `config.yaml` con "
        "`sleeve: opportunistic` e riavvia Streamlit."
    )

for status in _GROUPS_ORDER:
    strategies = groups.get(status, [])
    if not strategies:
        continue
    cfg = _STATUS_CFG.get(status, {"emoji": "⚪", "label": status})
    st.markdown(f"### {cfg['emoji']} {cfg['label']}")
    for s in strategies:
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 1, 1])
            with c1:
                st.markdown(f"**`{s.id}`**")
                if s.description:
                    st.caption(s.description)
                else:
                    st.caption("_(nessuna descrizione nel config.yaml)_")
            with c2:
                st.metric("Sleeve", s.sleeve)
            with c3:
                if st.button(
                    "Esplora →",
                    key=f"explore_{s.id}",
                    use_container_width=True,
                ):
                    st.session_state["exploring_strategy"] = s.id
                    st.rerun()

# ----- strategy detail view -----

if "exploring_strategy" in st.session_state:
    strategy_id = st.session_state["exploring_strategy"]
    strategy = next((s for s in alt_strategies if s.id == strategy_id), None)

    if strategy is None:
        st.error(f"Strategia non trovata nel registry: {strategy_id}")
        if st.button("← Torna alla lista"):
            st.session_state.pop("exploring_strategy", None)
            st.rerun()
    else:
        st.markdown("---")
        st.markdown(f"## 🔬 Dettaglio: `{strategy.id}`")
        if st.button("← Torna alla lista", key="back_to_list"):
            st.session_state.pop("exploring_strategy", None)
            st.rerun()

        tab_readme, tab_config, tab_backtest = st.tabs(
            ["📖 README", "⚙️ Configurazione", "🔬 Backtest Lab"]
        )

        directory = Path(strategy.directory)

        with tab_readme:
            readme_path = (
                Path(strategy.readme_path)
                if strategy.readme_path
                else directory / "README.md"
            )
            if readme_path.exists():
                try:
                    st.markdown(readme_path.read_text(encoding="utf-8"))
                except Exception as e:
                    st.error(f"Non riesco a leggere il README: {e}")
            else:
                st.info(f"Nessun README in `{directory}`.")

        with tab_config:
            config_path = directory / "config.yaml"
            if config_path.exists():
                try:
                    st.code(config_path.read_text(encoding="utf-8"), language="yaml")
                except Exception as e:
                    st.error(f"Non riesco a leggere il config: {e}")
            else:
                st.info(f"Nessun config.yaml in `{directory}`.")

        with tab_backtest:
            st.markdown(
                "Il **Backtest Lab** è una pagina dedicata con UI streaming "
                "(equity curve live, walk-forward, benchmark comparison)."
            )
            st.caption(
                "In v3.0.0 il Lab è hidden dalla nav primaria ma raggiungibile "
                "via URL diretto `/backtest-lab`. Apri da qui con il bottone:"
            )
            if st.button(
                f"🔬 Apri Backtest Lab per `{strategy.id}`",
                type="primary",
                key=f"bt_{strategy.id}",
            ):
                st.session_state["lab_strategy"] = strategy.id
                st.switch_page("pages/9_Backtest_Lab.py")

            if strategy.status == "scaffold":
                st.warning(
                    "⚠️ Strategia in stato **scaffold**: il codice è abbozzato ma "
                    "non ancora validato. Vedi il README per i passi di attivazione."
                )

# ----- add new strategy guide -----

st.markdown("---")
with st.expander("➕ Come aggiungere una nuova strategia"):
    st.markdown(
        """
Quant Lab è plug-and-play. Per aggiungere una strategia:

1. **Crea** `strategies/<nome>/strategy.py` con classe che eredita da `Strategy`.
2. **Crea** `strategies/<nome>/config.yaml` con `sleeve: opportunistic` + parametri.
3. **Crea** `strategies/<nome>/README.md` con descrizione + tesi + validation plan.
4. **Riavvia** Streamlit — la strategia viene auto-rilevata e appare qui.

Guida completa: `docs/adding_a_strategy.md`.

### Validation mandatory prima di `status: validated`

- Walk-forward 5+ fold con median OOS Sharpe > 0.5.
- Benchmark vs alternativa passiva rilevante (deve battere).
- Survivorship correction se equity-based.
- Backtest su almeno 10 anni di dati.

### Status transitions

- `scaffold` → `validated`  passa walk-forward + benchmark.
- `validated` → `active`    deploy con capitale reale + monitoring continuo.
- qualsiasi → `archived`    validation fallita o performance degradata.
"""
    )
