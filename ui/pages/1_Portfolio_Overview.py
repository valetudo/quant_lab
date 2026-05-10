"""Portfolio Overview — stub. Aggregate multi-strategy view in Phase 2."""
from __future__ import annotations
import streamlit as st

st.set_page_config(page_title="Portfolio Overview", page_icon="📊", layout="wide")
st.title("📊 Portfolio Overview")
st.caption("Aggregate equity, allocation, attribution across strategies.")

st.info(
    "**Status: stub** — implemented in Phase 2 once two or more strategies "
    "are producing standard outputs. For now: see each strategy's individual "
    "backtest output via the Backtest Runner page."
)

st.markdown(
    "### Planned\n"
    "- Combined equity curve weighted by `configs/allocation.yaml`\n"
    "- Per-strategy attribution\n"
    "- Cross-strategy correlation matrix\n"
    "- Risk parity overlay"
)
