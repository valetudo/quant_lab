"""Backtest Runner — pick a strategy, set parameters, run the engine."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from quant_lab.core.analytics.metrics import compute_metrics
from quant_lab.core.backtest.engine import PortfolioBacktester
from quant_lab.core.io.standard_schema import write_standard_outputs
from quant_lab.ui.components.equity_chart import equity_chart
from quant_lab.ui.components.metrics_table import metrics_table
from quant_lab.ui.utils.cache import get_storage

st.set_page_config(page_title="Backtest Runner", page_icon="🔬", layout="wide")
st.title("🔬 Backtest Runner")

storage = get_storage()
repo_root = Path(__file__).resolve().parents[2]

# ---- form ---------------------------------------------------------------

STRATEGY_CHOICES = ["dummy_buy_and_hold", "bonds_income"]

c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    strat_id = st.selectbox("Strategy", STRATEGY_CHOICES, index=0)
with c2:
    start = st.date_input("Start", value=date(2023, 1, 2))
with c3:
    end = st.date_input("End", value=date(2024, 12, 31))

c4, c5, c6 = st.columns(3)
with c4:
    capital = st.number_input("Capital (EUR)", value=50_000.0, min_value=1000.0, step=1000.0)
with c5:
    commission_bps = st.number_input("Commission (bps)", value=5.0, min_value=0.0, step=1.0)
with c6:
    slippage_bps = st.number_input("Slippage (bps)", value=5.0, min_value=0.0, step=1.0)

tickers_input = st.text_input(
    "Tickers (CSV, only used by dummy_buy_and_hold)",
    value="AAPL,MSFT,SPY",
)

run = st.button("▶︎ Run backtest", type="primary")

# ---- run ----------------------------------------------------------------

def _build_panel(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    panel = storage.load_panel(tickers, start, end)
    if panel.empty:
        # Synthetic fallback so the UI works even without GDS data
        idx = pd.bdate_range(start, end)
        if len(idx) == 0:
            return pd.DataFrame()
        rng = np.random.default_rng(42)
        rets = rng.normal(0.0005, 0.01, size=(len(idx), max(len(tickers), 1)))
        prices = 100 * np.cumprod(1 + rets, axis=0)
        cols = tickers if tickers else ["SIM"]
        panel = pd.DataFrame(prices, index=idx, columns=cols)
        st.warning(f"DuckDB had no data for {tickers} in window — using synthetic fallback.")
    return panel


def _make_strategy(strat_id: str, tickers: list[str], capital: float):
    if strat_id == "dummy_buy_and_hold":
        from quant_lab.strategies._examples import DummyBuyAndHold
        return DummyBuyAndHold(tickers=tickers, initial_capital_eur=capital)
    if strat_id == "bonds_income":
        from quant_lab.core.data.providers.borsa_italiana_provider import BorsaItalianaProvider
        from quant_lab.strategies.bonds_income import BondsIncome
        provider = BorsaItalianaProvider(db_path=storage.bonds_db_path) \
                   if storage.bonds_db_exists() else None
        return BondsIncome(bonds_provider=provider, initial_capital_eur=capital)
    raise ValueError(strat_id)


if run:
    tickers = [t.strip() for t in tickers_input.split(",") if t.strip()]
    with st.spinner("Building panel..."):
        if strat_id == "bonds_income":
            # bonds panel: ISIN columns, par=100 synthetic
            provider = None
            if storage.bonds_db_exists():
                from quant_lab.core.data.providers.borsa_italiana_provider import BorsaItalianaProvider
                provider = BorsaItalianaProvider(db_path=storage.bonds_db_path)
            isins = [b["isin"] for b in (provider.list_bonds() if provider else [])][:30]
            idx = pd.bdate_range(start, end)
            if not isins or len(idx) == 0:
                st.error("No bonds in DB or empty window — cannot run bonds_income backtest.")
                st.stop()
            panel = pd.DataFrame(100.0, index=idx, columns=isins)
        else:
            panel = _build_panel(tickers, start, end)
    if panel.empty:
        st.error("Empty panel — nothing to backtest.")
        st.stop()

    with st.spinner("Running backtest..."):
        strat = _make_strategy(strat_id, tickers, capital)
        bt = PortfolioBacktester(strat, panel, initial_capital_eur=capital,
                                 commission_bps=commission_bps, slippage_bps=slippage_bps)
        res = bt.run()

    eq = res.equity["equity"] if not res.equity.empty else pd.Series(dtype=float)
    metrics = compute_metrics(eq, res.trades, capital,
                              open_count=res.open_count, exposure=res.exposure)

    out_dir = repo_root / "outputs" / strat_id / f"{start}_{end}"
    paths = write_standard_outputs(
        out_dir,
        strategy_id=strat_id, universe=",".join(panel.columns[:5]) + "...",
        currency="EUR", trades=res.trades, equity=res.equity,
        open_count=res.open_count, metrics=metrics,
        period_start=start, period_end=end,
    )

    st.success(f"Backtest complete. {len(res.trades)} trades.")
    st.plotly_chart(equity_chart(eq, title=f"{strat_id}: equity"),
                    use_container_width=True)
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Metrics")
        metrics_table(metrics)
    with c2:
        st.subheader("Outputs")
        for k, p in paths.items():
            st.markdown(f"- `{k}` → `{p}`")
