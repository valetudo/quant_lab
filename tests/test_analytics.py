"""Analytics — metrics on synthetic equity / trades."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core.analytics.metrics import (
    compute_metrics,
    max_drawdown,
    sharpe,
    trade_stats,
)


@dataclass
class _MockTrade:
    net_pnl: float
    duration_days: int


def test_metrics_on_flat_equity():
    eq = pd.Series([100.0] * 252, index=pd.date_range("2024-01-01", periods=252))
    out = compute_metrics(eq, [], initial_capital=100.0)
    assert out["final_equity"] == 100.0
    assert out["total_pnl"] == 0.0
    assert out["max_drawdown"] == 0.0
    assert out["n_trades"] == 0


def test_sharpe_on_known_series():
    rng = np.random.default_rng(0)
    rets = pd.Series(rng.normal(0.001, 0.01, 1000))
    s = sharpe(rets)
    # Empirical mean/std ~ (1e-3 / 1e-2) * sqrt(252) ≈ 1.58 — sanity check
    assert 0.5 < s < 3.0


def test_drawdown_on_synthetic_dip():
    eq = pd.Series([100, 110, 120, 90, 95, 100], index=pd.date_range("2024-01-01", periods=6))
    mdd, peak, trough = max_drawdown(eq)
    assert mdd == pytest_approx(-0.25)
    assert peak == eq.index[2]
    assert trough == eq.index[3]


def test_trade_stats_basic():
    trades = [_MockTrade(50, 10), _MockTrade(-30, 5), _MockTrade(100, 8)]
    s = trade_stats(trades)
    assert s["n_trades"] == 3
    assert s["hit_rate"] == pytest_approx(2 / 3)
    assert s["avg_pnl"] == pytest_approx((50 - 30 + 100) / 3)


# --- tiny inline replacement for pytest.approx so we don't fight imports ---
def pytest_approx(value, tol=1e-9):
    class _Approx:
        def __eq__(self, other):
            return abs(other - value) <= max(tol, tol * abs(value))

    return _Approx()
