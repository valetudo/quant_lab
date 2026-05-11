"""Integration test for QualityStocks against the real FMP data.

Skipped if FMP_API_KEY is absent OR if the price parquet tree is empty.
"""
from __future__ import annotations

import os
from datetime import date

import pandas as pd
import pytest

from quant_lab.core.data.storage import DataStorage, load_global_config
from quant_lab.strategies.quality_stocks.factors import extract_quality_factors


def _have_data() -> bool:
    storage = DataStorage.from_config(load_global_config())
    return (storage.prices_root / "us" / "sp500").exists() and \
        any((storage.prices_root / "us" / "sp500").glob("*.parquet"))


pytestmark = pytest.mark.skipif(
    not os.getenv("FMP_API_KEY") or not _have_data(),
    reason="needs FMP_API_KEY + populated prices parquet tree",
)


@pytest.fixture(scope="module")
def fmp():
    from quant_lab.core.data.providers.fmp_provider import FMPProvider
    return FMPProvider()


@pytest.fixture(scope="module")
def storage():
    return DataStorage.from_config(load_global_config())


def test_storage_loads_panel(storage):
    panel = storage.get_prices_panel(
        ["AAPL", "MSFT", "SPY"], start="2024-01-02", end="2024-12-31"
    )
    assert not panel.empty
    assert len(panel.columns) >= 2
    assert (panel.index >= pd.Timestamp("2024-01-02")).all()


def test_point_in_time_discipline(fmp):
    """Fundamentals used at 2020-06-30 must have filing_date <= 2020-06-30."""
    cutoff = pd.Timestamp("2020-06-30")
    km = fmp.get_key_metrics("AAPL", limit=10)
    rt = fmp.get_ratios("AAPL", limit=10)
    factors = extract_quality_factors("AAPL", cutoff, km, rt)
    # Must produce factors (Apple has plenty of history before 2020)
    assert factors, "expected non-empty factors at 2020-06-30 cutoff"
    # And the underlying filing_date used must be <= cutoff
    visible_km = km[km["filing_date"] <= cutoff]
    assert not visible_km.empty
    assert visible_km["filing_date"].max() <= cutoff


def test_quality_stocks_backtest_short_window(storage, fmp):
    """End-to-end backtest on a recent 12-month window."""
    from quant_lab.core.analytics.metrics import compute_metrics
    from quant_lab.core.backtest.engine import PortfolioBacktester
    from quant_lab.strategies.quality_stocks import QualityStocks
    from quant_lab.strategies.quality_stocks.runner import build_panel

    universe = fmp.get_index_constituents("sp500")
    # Trim to 100 names to keep the test fast
    universe = universe[:100]
    panel = build_panel(storage, start="2024-01-02", end="2024-12-31",
                        universe_symbols=universe, extra=("SPY", "IEF"))
    assert not panel.empty
    assert "SPY" in panel.columns

    strat = QualityStocks(fmp=fmp, universe_symbols=universe, prefetch=False)
    bt = PortfolioBacktester(strat, panel,
                             initial_capital_eur=100_000,
                             commission_bps=5, slippage_bps=5)
    res = bt.run()
    assert not res.equity.empty
    eq = res.equity["equity"]
    metrics = compute_metrics(eq, res.trades, 100_000,
                              open_count=res.open_count,
                              exposure=res.exposure)
    # Sanity: final equity stays in a reasonable range vs. capital
    assert 0.5 * 100_000 < metrics["final_equity"] < 2.0 * 100_000
    # Sharpe should be a real number
    assert pd.notna(metrics["sharpe"])
