"""Lifecycle helpers (rebalance scheduling, retrain cadence)."""

from __future__ import annotations

import pandas as pd


def is_first_of_month(date: pd.Timestamp, history: pd.DataFrame) -> bool:
    """True when `date` is the first trading day of its calendar month in `history.index`."""
    idx = history.index
    if date not in idx:
        return False
    same_month = idx[(idx.year == date.year) & (idx.month == date.month)]
    return len(same_month) > 0 and same_month[0] == date


def every_n_days(date: pd.Timestamp, history: pd.DataFrame, n: int) -> bool:
    """True when iloc(date) % n == 0."""
    idx = history.index
    if date not in idx:
        return False
    return idx.get_loc(date) % n == 0
