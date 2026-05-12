"""Current-price lookups for portfolio valuation.

For **bonds** the latest snapshot lives in ``bonds.db`` (one row per ISIN in
the ``bond_prices`` table). For **equity ETFs** we read the most recent
``adj_close`` from the local FMP-backed parquet store via
:class:`core.data.storage.DataStorage`; if the configured symbol is
missing we fall through the :data:`RETAIL_PROXIES` table (VWCE→VT,
CSPX→SPY, etc.). For **alternative-strategy stakes** we have no live mark
yet, so the provider returns ``None`` (callers mark-to-cost).

This is intentionally tolerant: missing prices return ``None`` rather
than raising, so the UI can flag "stale price" without breaking the page.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

log = logging.getLogger(__name__)


# Known UCITS ETF ISIN → preferred ticker mapping. The ticker is what we
# query in DataStorage.get_prices_with_proxy; if missing it falls back to
# the proxy (VT, SPY, URTH) via RETAIL_PROXIES.
ETF_ISIN_TO_TICKER: dict[str, str] = {
    "IE00BK5BQT80": "VWCE.MI",  # Vanguard FTSE All-World
    "IE00B4L5Y983": "SWDA.L",  # iShares Core MSCI World
    "IE00B3YLTY66": "SPYY.DE",  # SPDR MSCI ACWI
    "IE00B3XXRP09": "VUSA.L",  # Vanguard S&P 500 (dist)
    "IE00B5BMR087": "CSPX.L",  # iShares Core S&P 500 (acc)
    "IE00BFMXXD54": "VUAA.L",  # Vanguard S&P 500 (acc)
}


class PriceProvider:
    """Looks up current/latest prices for a list of positions."""

    def __init__(
        self,
        bonds_db_path: Optional[Path | str] = None,
        storage=None,
    ) -> None:
        self.bonds_db_path = Path(bonds_db_path) if bonds_db_path else None
        self._storage = storage

    def _storage_handle(self):
        if self._storage is not None:
            return self._storage
        try:
            from core.data.storage import DataStorage, load_global_config

            self._storage = DataStorage.from_config(load_global_config())
        except Exception as e:
            log.warning("PriceProvider: storage unavailable (%s)", e)
            self._storage = None
        return self._storage

    def _bonds_db(self) -> Optional[Path]:
        if self.bonds_db_path:
            return self.bonds_db_path
        storage = self._storage_handle()
        if storage is None:
            return None
        return getattr(storage, "bonds_db_path", None)

    # ---------- public ----------

    def get_prices(self, positions: Iterable) -> dict[str, Optional[float]]:
        """Returns ``{isin: latest_price}`` for the supplied positions.

        ``latest_price`` is the bond price as % of face for bonds, EUR
        per share for ETFs, and ``None`` (cost-basis fallback) for
        alternative-strategy stakes.
        """
        positions = list(positions)
        out: dict[str, Optional[float]] = {}

        bond_isins = [p.isin for p in positions if p.asset_class == "bond"]
        if bond_isins:
            for isin, price in self._bond_prices(bond_isins).items():
                out[isin] = price

        for p in positions:
            if p.asset_class == "equity":
                out[p.isin] = self._equity_price(p.isin, p.name)
            elif p.asset_class == "alternative":
                out[p.isin] = None  # cost-basis fallback in the tracker

        return out

    # ---------- bonds ----------

    def _bond_prices(self, isins: list[str]) -> dict[str, Optional[float]]:
        db = self._bonds_db()
        if db is None or not Path(db).exists():
            return {isin: None for isin in isins}
        out: dict[str, Optional[float]] = {isin: None for isin in isins}
        try:
            with sqlite3.connect(str(db)) as conn:
                placeholders = ",".join("?" for _ in isins)
                cur = conn.execute(
                    "SELECT isin, price FROM bond_prices "
                    f"WHERE isin IN ({placeholders}) "
                    "ORDER BY date DESC",
                    isins,
                )
                seen: set[str] = set()
                for row in cur.fetchall():
                    isin, price = row
                    if isin in seen:
                        continue
                    out[isin] = float(price) if price is not None else None
                    seen.add(isin)
        except Exception as e:
            log.warning("bond price lookup failed: %s", e)
        return out

    # ---------- equity ----------

    def _equity_price(self, isin: str, name: Optional[str]) -> Optional[float]:
        storage = self._storage_handle()
        if storage is None:
            return None
        ticker = ETF_ISIN_TO_TICKER.get(isin)
        if ticker is None:
            # Try a name-based heuristic: VWCE in the name → VWCE.MI.
            for marker, tic in (
                ("VWCE", "VWCE.MI"),
                ("IWDA", "SWDA.L"),
                ("SWDA", "SWDA.L"),
                ("CSPX", "CSPX.L"),
                ("VUSA", "VUSA.L"),
                ("VUAA", "VUAA.L"),
                ("S&P 500", "CSPX.L"),
                ("All-World", "VWCE.MI"),
                ("MSCI World", "SWDA.L"),
            ):
                if name and marker.lower() in name.lower():
                    ticker = tic
                    break
        if ticker is None:
            return None
        try:
            df = storage.get_prices_with_proxy(ticker)
        except Exception as e:
            log.warning("equity price lookup failed for %s: %s", ticker, e)
            return None
        if df is None or df.empty or "adj_close" not in df.columns:
            return None
        last = df["adj_close"].dropna()
        if last.empty:
            return None
        return float(last.iloc[-1])
