"""Helpers to build a price panel for the QualityStocks engine run.

The engine expects a wide DataFrame indexed by date, columned by symbol,
of adj_close. We pull S&P 500 + SPY + IEF from the FMP parquet tree.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

from core.data.storage import DataStorage

log = logging.getLogger(__name__)


def build_panel(
    storage: DataStorage,
    *,
    start: date | str,
    end: date | str,
    universe_symbols: list[str],
    extra: tuple[str, ...] = ("SPY", "IEF"),
    field: str = "adj_close",
) -> pd.DataFrame:
    """Wide panel of `field` for universe + extras. Returns empty if nothing on disk."""
    all_syms = sorted(set(universe_symbols) | set(extra))
    panel = storage.get_prices_panel(all_syms, start, end, field=field)
    if panel.empty:
        log.warning("empty panel — has the FMP migration run?")
    # Drop columns with too few datapoints (e.g. newly-listed names lacking history)
    panel = panel.dropna(axis=1, thresh=int(0.5 * len(panel)))
    return panel.sort_index()
