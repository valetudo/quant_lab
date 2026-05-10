"""BaseProvider — ABC for all data sources."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date


class BaseProvider(ABC):
    """A provider knows how to refresh a specific data source.

    refresh(): fetch latest from source and persist to storage.
    fetch_panel(): return a wide OHLCV-like DataFrame for tickers in date range.
    """

    @property
    @abstractmethod
    def provider_id(self) -> str: ...

    @abstractmethod
    def refresh(self, *args, **kwargs) -> dict: ...
