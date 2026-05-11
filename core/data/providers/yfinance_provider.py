"""YFinanceProvider — thin wrapper over yfinance for equity OHLCV.

For Phase 1: returns DataFrames directly. The persistence path (writing
into the GDS DuckDB) is delegated to global_data_storage's own ingest
scripts — this provider is read-side convenience, not a writer.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Sequence

import pandas as pd

from core.data.providers.base import BaseProvider

log = logging.getLogger(__name__)


class YFinanceProvider(BaseProvider):
    @property
    def provider_id(self) -> str:
        return "yfinance"

    def fetch_panel(
        self,
        tickers: Sequence[str],
        start: date | str,
        end: date | str,
        field: str = "Adj Close",
    ) -> pd.DataFrame:
        """Return wide DataFrame [date × ticker] of `field`. Empty if yfinance unavailable."""
        try:
            import yfinance as yf
        except ImportError:
            log.warning("yfinance not installed — returning empty panel")
            return pd.DataFrame()
        if not tickers:
            return pd.DataFrame()
        data = yf.download(
            tickers=list(tickers),
            start=str(start),
            end=str(end),
            auto_adjust=False,
            progress=False,
            group_by="column",
        )
        if data is None or data.empty:
            return pd.DataFrame()
        # Handle yfinance's MultiIndex columns: (Field, Ticker)
        if isinstance(data.columns, pd.MultiIndex):
            if field in data.columns.get_level_values(0):
                df = data[field]
            else:
                df = data.iloc[:, :0]
        else:
            df = data[[field]] if field in data.columns else data
            df.columns = list(tickers)[:1]
        df.index = pd.to_datetime(df.index)
        df.index.name = "date"
        return df.dropna(how="all")

    def refresh(self, *args, **kwargs) -> dict:
        """No-op: yfinance is read-only here; persistence is handled by global_data_storage."""
        return {"status": "noop", "message": "use global_data_storage ingest scripts to persist"}
