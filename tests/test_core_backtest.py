"""End-to-end engine test with DummyBuyAndHold on synthetic data."""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.backtest.engine import PortfolioBacktester
from strategies._examples import DummyBuyAndHold


def _synthetic_panel():
    idx = pd.date_range("2024-01-02", periods=252, freq="B")
    rng = np.random.default_rng(42)
    cols = ["AAA", "BBB", "CCC"]
    rets = rng.normal(loc=0.0005, scale=0.01, size=(len(idx), len(cols)))
    prices = 100 * np.cumprod(1 + rets, axis=0)
    return pd.DataFrame(prices, index=idx, columns=cols)


def test_engine_runs_with_dummy_buy_and_hold():
    panel = _synthetic_panel()
    strat = DummyBuyAndHold(tickers=panel.columns.tolist(), initial_capital_eur=30_000)
    bt = PortfolioBacktester(
        strat, panel, initial_capital_eur=30_000, commission_bps=5, slippage_bps=5
    )
    res = bt.run()

    assert not res.equity.empty
    assert "equity" in res.equity.columns
    # 3 trades opened at first bar, closed at last bar
    assert len(res.trades) == 3
    for t in res.trades:
        assert t.sides == ["long"]
        assert t.duration_days >= 0
        assert t.exit_reason in {"eod", "strategy_close"}
    # Final equity within a reasonable range
    final_eq = res.equity["equity"].iloc[-1]
    assert final_eq > 0


def test_engine_handles_empty_signals_gracefully():
    panel = _synthetic_panel()
    # Universe contains a ticker NOT in panel — strategy generates nothing
    strat = DummyBuyAndHold(tickers=["XXX"], initial_capital_eur=10_000)
    bt = PortfolioBacktester(strat, panel, initial_capital_eur=10_000)
    res = bt.run()
    assert len(res.trades) == 0
    # Equity should remain at initial capital throughout
    assert abs(res.equity["equity"].iloc[-1] - 10_000) < 1e-6
