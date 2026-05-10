"""Data Status — coverage by ticker, last update, refresh control."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from quant_lab.ui.utils.cache import cached_universe_meta, cached_known_tickers, get_storage

st.set_page_config(page_title="Data Status", page_icon="📁", layout="wide")
st.title("📁 Data Status")

storage = get_storage()

c1, c2, c3 = st.columns(3)
with c1:
    st.metric("DuckDB exists", "yes" if storage.duckdb_path.exists() else "no")
with c2:
    st.metric("Bonds DB exists", "yes" if storage.bonds_db_exists() else "no")
with c3:
    st.metric("Universe entries (active)",
              len(cached_universe_meta()) if storage.duckdb_path.exists() else 0)

st.markdown("---")

if not storage.duckdb_path.exists():
    st.warning(
        f"DuckDB store not found at `{storage.duckdb_path}`. "
        "Configure `duckdb_path` in `configs/global.yaml` or set the "
        "`GDS_DB_PATH` env var."
    )
else:
    st.subheader("Universe")
    meta = cached_universe_meta()
    if meta.empty:
        st.info("No `prices.universe` rows.")
    else:
        st.dataframe(meta, use_container_width=True, hide_index=True)

    st.subheader("Tickers with price data")
    tickers = cached_known_tickers()
    if tickers:
        st.write(f"**{len(tickers)} tickers** have at least one bar in `prices.equity_ohlcv`.")
        st.dataframe(pd.DataFrame({"ticker": tickers}),
                     use_container_width=True, hide_index=True, height=300)
    else:
        st.info("No tickers found in DuckDB.")

st.markdown("---")
st.subheader("Manual refresh")
st.caption(
    "Wiring for `scripts/update_all_data.py`. In Phase 1 we surface the "
    "command rather than running it inline (the GDS ingest pipeline lives "
    "outside this repo)."
)
refresh_cmd = str(Path(__file__).resolve().parents[2] / "scripts" / "update_all_data.py")
st.code(f"python {refresh_cmd}", language="bash")
