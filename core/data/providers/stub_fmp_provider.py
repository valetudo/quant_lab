"""FMP (Financial Modeling Prep) provider — stub. Implementation in Phase 2.

Quality Stocks will need fundamentals (ROIC, debt/equity, gross margin
stability, etc.) — those come from FMP, not yfinance. This stub lets the
rest of the data layer import cleanly today.
"""
from __future__ import annotations

import logging

from quant_lab.core.data.providers.base import BaseProvider

log = logging.getLogger(__name__)


class FMPProvider(BaseProvider):
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    @property
    def provider_id(self) -> str:
        return "fmp"

    def fetch_fundamentals(self, ticker: str, **kwargs) -> dict:
        log.warning("FMPProvider is a stub — Phase 2")
        return {"ticker": ticker, "status": "not_implemented"}

    def refresh(self, *args, **kwargs) -> dict:
        return {"status": "not_implemented", "message": "FMPProvider is a stub"}
