"""Strategies — registry-driven listing grouped by sleeve.

Auto-discovers every concrete Strategy subclass under ``strategies/`` (via
``core.strategy.registry.StrategyRegistry``) and groups them by the sleeve
the portfolio config assigns them to.

To add a new strategy: drop a folder under ``strategies/<id>/`` with
``strategy.py`` and ``config.yaml``. Restart Streamlit — it shows up here
automatically. No code change to this page required.
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

st.set_page_config(page_title="Strategies", page_icon="📈", layout="wide")
st.title("📈 Strategies")
st.caption(
    "All strategies auto-discovered from `strategies/`. Add a new one by "
    "creating a folder there — see `docs/adding_a_strategy.md`."
)

registry = StrategyRegistry()

if len(registry) == 0:
    st.warning(
        "No strategies registered. Check that `strategies/` contains "
        "subdirectories with `strategy.py` + `config.yaml`."
    )
    st.stop()


STATUS_BADGE = {
    "active": ("🟢", "#16a34a"),
    "scaffold": ("🟡", "#f59e0b"),
    "deprecated": ("⚫", "#6b7280"),
}

SLEEVE_LABELS = {
    "bonds": "💰 Bonds (50%)",
    "equity": "📈 Equity (30%)",
    "opportunistic": "🎲 Opportunistic (20%)",
}


def _default_kwargs_for(strategy_id: str) -> dict:
    """Best-effort defaults for registry-side instantiation smoke.

    Strategies in this monorepo have different ctor signatures (BondsIncome
    wants a snapshot, PassiveEquity wants a symbol + capital). This helper
    keeps the listing page honest — if a strategy needs args we don't know,
    we just skip the universe introspection and say so.
    """
    if strategy_id == "bonds_income":
        return {"bond_snapshot": []}
    if strategy_id == "passive_equity":
        return {"symbol": "SPY", "initial_capital_eur": 10_000.0}
    if strategy_id == "pattern_finder":
        return {}  # adapter is scaffold-status: noop init
    return {}


for sleeve_id in ("bonds", "equity", "opportunistic"):
    sleeve_strats = registry.by_sleeve(sleeve_id)
    st.markdown(f"## {SLEEVE_LABELS.get(sleeve_id, sleeve_id)}")
    st.caption(f"{len(sleeve_strats)} strategy(ies) in this sleeve")

    if not sleeve_strats:
        if sleeve_id == "opportunistic":
            st.info(
                "**No active strategies.** Drop a folder under "
                "`strategies/<id>/` with `strategy.py` + `config.yaml` — "
                "it auto-registers here on the next Streamlit restart.\n\n"
                "Pattern Finder is scaffolded but not yet active — see "
                "`strategies/pattern_finder/README.md`."
            )
        else:
            st.info(f"No strategies registered for the **{sleeve_id}** sleeve.")
        continue

    for s in sleeve_strats:
        with st.container(border=True):
            cols = st.columns([3, 1, 1])
            with cols[0]:
                icon, _ = STATUS_BADGE.get(s.status, ("⚪", "#888"))
                st.markdown(
                    f"### {icon} `{s.id}` "
                    f"<span style='font-size:0.7em;color:#6b7280;'>"
                    f"({s.status})</span>",
                    unsafe_allow_html=True,
                )
                if s.description:
                    st.caption(s.description)
                st.code(f"strategies/{Path(s.directory).name}/", language="text")
            with cols[1]:
                st.metric("Status", s.status)
            with cols[2]:
                st.metric("Sleeve", s.sleeve)

            if s.readme_path and Path(s.readme_path).exists():
                with st.expander("README", expanded=False):
                    try:
                        st.markdown(Path(s.readme_path).read_text(encoding="utf-8"))
                    except Exception as e:
                        st.warning(f"Could not read README: {e}")

            try:
                inst = s.cls(**_default_kwargs_for(s.id))
                u_size = len(inst.universe)
                st.caption(f"Universe size at init: {u_size} symbol(s)")
            except Exception:
                # Don't crash the page if a strategy needs special init args
                st.caption(
                    ":grey_question: Could not introspect universe — needs "
                    "constructor arguments not provided here."
                )


st.markdown("---")
st.subheader("Archived strategies")
import yaml

cfg_path = _PROJECT_ROOT / "configs" / "portfolio.yaml"
if cfg_path.exists():
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    archived = cfg.get("archived_strategies", [])
    if archived:
        for a in archived:
            with st.container(border=True):
                st.markdown(f"**`{a.get('id')}`** — archived {a.get('archived_date')}")
                st.caption(f"Reason: {a.get('reason')}")
                st.caption(f"Code: `{a.get('code_archive_path')}`")
                st.caption(f"Decision report: `{a.get('decision_report')}`")
    else:
        st.info("No archived strategies.")
