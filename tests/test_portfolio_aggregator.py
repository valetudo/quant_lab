"""Tests for the Master Allocator + PortfolioAggregator."""

from __future__ import annotations


import numpy as np
import pandas as pd
import pytest

from portfolio.aggregator import PortfolioAggregator
from portfolio.master_allocator import (
    EqualWeightAllocator,
    FixedWeightAllocator,
    RegimeAwareAllocator,
)
from strategies._examples import DummyBuyAndHold


def _synthetic_panel(seed: int = 0):
    idx = pd.bdate_range("2024-01-02", periods=252)
    rng = np.random.default_rng(seed)
    cols = ["AAA", "BBB", "CCC"]
    rets = rng.normal(0.0005, 0.01, size=(len(idx), len(cols)))
    prices = 100 * np.cumprod(1 + rets, axis=0)
    return pd.DataFrame(prices, index=idx, columns=cols)


def test_equal_weight_allocator_two_strategies():
    a = EqualWeightAllocator(["s1", "s2"])
    w = a.compute_weights(pd.Timestamp.now(), strategy_states={})
    assert w == {"s1": 0.5, "s2": 0.5}


def test_equal_weight_with_cash_reserve():
    a = EqualWeightAllocator(["s1", "s2"], cash_reserve=0.10)
    w = a.compute_weights(pd.Timestamp.now())
    assert w["s1"] == pytest.approx(0.45)
    assert w["s2"] == pytest.approx(0.45)
    assert sum(w.values()) == pytest.approx(0.90)


def test_fixed_weight_allocator():
    a = FixedWeightAllocator({"s1": 0.6, "s2": 0.4})
    w = a.compute_weights(pd.Timestamp.now())
    assert w == {"s1": 0.6, "s2": 0.4}


def test_fixed_weight_rejects_oversum():
    with pytest.raises(ValueError):
        FixedWeightAllocator({"s1": 0.6, "s2": 0.6})


def test_regime_aware_not_implemented():
    with pytest.raises(NotImplementedError):
        RegimeAwareAllocator().compute_weights(pd.Timestamp.now())


def test_portfolio_aggregator_two_dummies():
    panel = _synthetic_panel()
    s1 = DummyBuyAndHold(tickers=["AAA", "BBB"], strategy_id="dummy_1")
    s2 = DummyBuyAndHold(tickers=["BBB", "CCC"], strategy_id="dummy_2")
    pa = PortfolioAggregator(
        strategies=[s1, s2],
        panels={"dummy_1": panel, "dummy_2": panel},
        total_capital_eur=100_000.0,
    )
    res = pa.run()
    assert "dummy_1" in res.strategy_results
    assert "dummy_2" in res.strategy_results
    # Each got ~50k allocated
    assert 49_000 < res.strategy_results["dummy_1"].capital_alloc < 51_000
    # Portfolio equity is non-empty
    assert not res.portfolio_equity.empty
    # Correlation matrix is 2x2
    if not res.correlations.empty:
        assert res.correlations.shape == (2, 2)
        # Diagonal == 1.0
        for sid in ("dummy_1", "dummy_2"):
            assert res.correlations.loc[sid, sid] == pytest.approx(1.0)


def test_portfolio_metrics_makes_sense():
    panel = _synthetic_panel()
    s1 = DummyBuyAndHold(tickers=["AAA"], strategy_id="dummy_x")
    pa = PortfolioAggregator(
        strategies=[s1],
        panels={"dummy_x": panel},
        total_capital_eur=50_000.0,
    )
    res = pa.run()
    assert res.portfolio_metrics
    # Final equity within reasonable range
    final = res.portfolio_metrics["final_equity"]
    assert 25_000 < final < 100_000
