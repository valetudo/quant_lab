"""StrategyCard — one card per strategy in the listing page."""
from __future__ import annotations
from pathlib import Path

import streamlit as st


def strategy_card(*, strategy_id: str, status: str, universe_size: int,
                  readme_path: Path | None = None, tests_path: Path | None = None) -> None:
    badge_color = {"working": "🟢", "scaffold": "🟡", "archived": "⚫"}.get(status, "⚪")
    with st.container(border=True):
        st.markdown(f"### {badge_color} `{strategy_id}`")
        c1, c2 = st.columns([1, 3])
        with c1:
            st.metric("Universe", universe_size)
            st.write(f"**Status**: {status}")
        with c2:
            if readme_path and readme_path.exists():
                with st.expander("README", expanded=False):
                    st.markdown(readme_path.read_text(encoding="utf-8"))
            if tests_path and tests_path.exists():
                st.caption(f"Tests: `{tests_path.relative_to(tests_path.parents[3]) if len(tests_path.parents) > 3 else tests_path}`")
