"""Smoke tests for QualityStocks — no live API hits required."""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from quant_lab.strategies.quality_stocks.factors import (
    calculate_momentum,
    calculate_quality_score,
    extract_quality_factors,
)
from quant_lab.strategies.quality_stocks.regime import is_market_uptrend, regime_label


def _fake_km(symbol: str, roic_values: list[float], filing_dates: list[str]) -> pd.DataFrame:
    rows = [
        {"returnOnInvestedCapital": r,
         "freeCashFlowYield": 0.05,
         "freeCashFlowToEquity": 0.06,
         "filing_date": pd.to_datetime(d),
         "period_end_date": pd.to_datetime(d) - pd.Timedelta(days=90)}
        for r, d in zip(roic_values, filing_dates)
    ]
    return pd.DataFrame(rows)


def _fake_ratios(debt_eq: float, filing_date: str) -> pd.DataFrame:
    return pd.DataFrame([{
        "debtToEquityRatio": debt_eq,
        "filing_date": pd.to_datetime(filing_date),
        "period_end_date": pd.to_datetime(filing_date) - pd.Timedelta(days=90),
    }])


def test_extract_quality_factors_basic():
    km = _fake_km("AAPL",
                  roic_values=[0.5, 0.4, 0.45, 0.48, 0.42],
                  filing_dates=["2025-01-01", "2024-01-01", "2023-01-01", "2022-01-01", "2021-01-01"])
    rt = _fake_ratios(1.5, "2025-01-01")
    f = extract_quality_factors("AAPL", pd.Timestamp("2025-06-01"), km, rt)
    assert "roic" in f and f["roic"] == pytest.approx(0.5)
    assert "inv_debt_eq" in f and f["inv_debt_eq"] == pytest.approx(1 / 1.5)
    assert "stable_roic" in f and f["stable_roic"] is not None


def test_extract_quality_factors_point_in_time():
    """ROIC released in 2025 must NOT influence a 2023-06 lookup."""
    km = _fake_km("AAPL",
                  roic_values=[0.5, 0.4, 0.45],
                  filing_dates=["2025-01-01", "2024-01-01", "2023-01-01"])
    rt = _fake_ratios(1.5, "2023-01-01")
    f = extract_quality_factors("AAPL", pd.Timestamp("2023-06-01"), km, rt)
    # Latest visible at 2023-06 is filing 2023-01-01 with roic=0.45
    assert f["roic"] == pytest.approx(0.45)


def test_quality_score_ranks_higher_roic_first():
    factors = pd.DataFrame({
        "roic":          [0.5, 0.1, 0.3],
        "fcf_yield":     [0.05, 0.02, 0.04],
        "cash_return":   [0.06, 0.03, 0.05],
        "inv_debt_eq":   [0.8, 0.2, 0.5],
        "stable_roic":   [10.0, 2.0, 5.0],
    }, index=["GOOD", "BAD", "MID"])
    score = calculate_quality_score(factors)
    assert score.index[0] == "GOOD"
    assert score.index[-1] == "BAD"


def test_momentum_basic():
    idx = pd.bdate_range("2024-01-02", periods=200)
    cols = ["AAA", "BBB"]
    # AAA: monotone up; BBB: monotone down
    panel = pd.DataFrame({
        "AAA": np.linspace(100, 150, 200),
        "BBB": np.linspace(150, 100, 200),
    }, index=idx)
    mom = calculate_momentum(panel, ["AAA", "BBB"], idx[-1],
                             lookback_days=126, skip_days=10)
    assert mom["AAA"] > 0 > mom["BBB"]


def test_is_market_uptrend():
    # Bull series: linear up
    bull = pd.Series(np.linspace(100, 200, 250),
                     index=pd.bdate_range("2024-01-02", periods=250))
    assert is_market_uptrend(bull, bull.index[-1])
    # Bear series: linear down
    bear = pd.Series(np.linspace(200, 100, 250),
                     index=pd.bdate_range("2024-01-02", periods=250))
    assert not is_market_uptrend(bear, bear.index[-1])


def test_regime_label():
    bull = pd.Series(np.linspace(100, 200, 250),
                     index=pd.bdate_range("2024-01-02", periods=250))
    assert regime_label(bull, bull.index[-1]) == "uptrend"
    bear = pd.Series(np.linspace(200, 100, 250),
                     index=pd.bdate_range("2024-01-02", periods=250))
    assert regime_label(bear, bear.index[-1]) == "downtrend"
    short = pd.Series([100, 101, 102], index=pd.bdate_range("2024-01-02", periods=3))
    assert regime_label(short, short.index[-1]) == "unknown"
