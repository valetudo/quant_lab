"""Trend filter for Quality Stocks.

is_market_uptrend(spy_series, date) returns True iff SMA(50) > SMA(200)
on `date` of the SPY adj_close series.
"""
from __future__ import annotations

import pandas as pd


def is_market_uptrend(
    spy_prices: pd.Series,
    date: pd.Timestamp,
    *,
    short_ma: int = 50,
    long_ma: int = 200,
) -> bool:
    """SMA(50) > SMA(200) on `date`. Requires >= `long_ma` history before `date`."""
    if spy_prices is None or spy_prices.empty:
        return False
    cutoff = pd.to_datetime(date)
    s = spy_prices.loc[:cutoff].dropna()
    if len(s) < long_ma:
        return False
    sma_s = s.rolling(short_ma).mean().iloc[-1]
    sma_l = s.rolling(long_ma).mean().iloc[-1]
    return bool(sma_s > sma_l)


def regime_label(
    spy_prices: pd.Series,
    date: pd.Timestamp,
    *,
    short_ma: int = 50,
    long_ma: int = 200,
) -> str:
    """'uptrend' | 'downtrend' | 'unknown'."""
    if spy_prices is None or spy_prices.empty:
        return "unknown"
    cutoff = pd.to_datetime(date)
    s = spy_prices.loc[:cutoff].dropna()
    if len(s) < long_ma:
        return "unknown"
    sma_s = s.rolling(short_ma).mean().iloc[-1]
    sma_l = s.rolling(long_ma).mean().iloc[-1]
    return "uptrend" if sma_s > sma_l else "downtrend"
