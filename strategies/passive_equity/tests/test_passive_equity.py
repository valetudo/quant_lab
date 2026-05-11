"""Tests for the PassiveEquity (Phase-4 equity sleeve)."""

from __future__ import annotations


import numpy as np
import pandas as pd
import pytest

from strategies.passive_equity import PassiveEquity


@pytest.fixture
def panel() -> pd.DataFrame:
    """Synthetic 1-year panel with both CSPX.L and SPY tradeable."""
    idx = pd.bdate_range("2024-01-02", "2024-12-31")
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "CSPX.L": 100 * np.cumprod(1 + rng.normal(0.0004, 0.008, len(idx))),
            "SPY": 100 * np.cumprod(1 + rng.normal(0.0004, 0.008, len(idx))),
        },
        index=idx,
    )


@pytest.fixture
def panel_no_cspx() -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-02", "2024-12-31")
    rng = np.random.default_rng(1)
    return pd.DataFrame(
        {
            "SPY": 100 * np.cumprod(1 + rng.normal(0.0004, 0.008, len(idx))),
        },
        index=idx,
    )


# ---- core behaviour ----


def test_buys_once(panel: pd.DataFrame):
    s = PassiveEquity(symbol="CSPX.L", initial_capital_eur=10_000.0)
    s.on_init(panel.iloc[:1])
    signals = s.generate_signals(panel.index[0], panel.iloc[:1], open_positions=[])
    assert len(signals) == 1
    assert signals[0].instruments == ["CSPX.L"]
    assert signals[0].sides == ["long"]
    assert signals[0].target_sizes_eur == [10_000.0]


def test_buys_only_once(panel: pd.DataFrame):
    s = PassiveEquity(symbol="CSPX.L", initial_capital_eur=10_000.0)
    s.on_init(panel.iloc[:1])
    # First bar — buys
    sig1 = s.generate_signals(panel.index[0], panel.iloc[:1], open_positions=[])
    # Second bar — already bought, no signal
    sig2 = s.generate_signals(panel.index[1], panel.iloc[:2], open_positions=[])
    assert len(sig1) == 1
    assert sig2 == []


def test_manage_positions_never_returns_actions(panel: pd.DataFrame):
    s = PassiveEquity(symbol="CSPX.L", initial_capital_eur=10_000.0)
    s.on_init(panel.iloc[:1])
    # Across many bars, manage_positions always returns []
    for i in range(0, len(panel), 30):
        actions = s.manage_positions(panel.index[i], panel.iloc[: i + 1], open_positions=[])
        assert actions == []


# ---- proxy fallback ----


def test_uses_proxy_when_cspx_missing(panel_no_cspx: pd.DataFrame):
    s = PassiveEquity(symbol="CSPX.L", initial_capital_eur=10_000.0)
    s.on_init(panel_no_cspx.iloc[:1])
    signals = s.generate_signals(panel_no_cspx.index[0], panel_no_cspx.iloc[:1], open_positions=[])
    assert len(signals) == 1
    assert signals[0].instruments == ["SPY"]
    assert signals[0].metadata["used_proxy"] is True
    assert signals[0].metadata["configured_symbol"] == "CSPX.L"
    assert signals[0].metadata["actual_symbol"] == "SPY"


def test_no_signal_when_neither_symbol_nor_proxy_available():
    panel = pd.DataFrame({"AAPL": [100, 101, 102]}, index=pd.bdate_range("2024-01-02", periods=3))
    s = PassiveEquity(symbol="CSPX.L", initial_capital_eur=10_000.0)
    s.on_init(panel.iloc[:1])
    signals = s.generate_signals(panel.index[0], panel.iloc[:1], open_positions=[])
    assert signals == []
    # And subsequent calls also stay empty (no buy ever happened)
    s2 = s.generate_signals(panel.index[1], panel.iloc[:2], open_positions=[])
    assert s2 == []


# ---- config loading ----


def test_default_config_loaded_when_no_kwargs(tmp_path, monkeypatch):
    s = PassiveEquity()
    # Default config.yaml carries VWCE.MI (v1.1.0+)
    assert s.universe == ["VWCE.MI"]
    assert s._initial_capital_eur == 30_000.0
    assert s.strategy_id == "passive_equity"


def test_explicit_kwargs_override_config():
    s = PassiveEquity(symbol="VUAA.L", initial_capital_eur=12_345.0)
    assert s.universe == ["VUAA.L"]
    assert s._initial_capital_eur == 12_345.0
