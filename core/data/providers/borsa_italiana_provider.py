"""BorsaItalianaProvider — Selenium scraper + SQLite for Italian bonds.

Wraps the original `bonds/` codebase (scraper.py, database.py,
calculations.py) preserved unchanged under `_bonds_impl/`. This module
is the public façade — strategies and the UI never import from the
sub-package directly.

The DB path is taken from `configs/global.yaml` (`bonds_db_path`) or
overridden via constructor. Default for development: the same DB the
original bonds project used. Migration to global_data_storage/bonds/
is performed by `scripts/migrate_bonds_db.py`.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from core.data.providers._bonds_impl import calculations as _calc
from core.data.providers._bonds_impl.database import Database
from core.data.providers.base import BaseProvider

log = logging.getLogger(__name__)


class BorsaItalianaProvider(BaseProvider):
    """Read + write access to the bonds catalog + price history."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        # Lazy default: caller usually passes the path from DataStorage.
        self._db_path = Path(db_path) if db_path else None
        self._db: Database | None = None

    @property
    def provider_id(self) -> str:
        return "borsa_italiana"

    @property
    def db(self) -> Database:
        if self._db is None:
            self._db = Database(self._db_path) if self._db_path else Database()
        return self._db

    # ---- read side -------------------------------------------------------

    def list_bonds(self, *, include_inactive: bool = False, enrich: bool = True) -> list[dict]:
        rows = self.db.list_bonds_with_latest_price(include_inactive=include_inactive)
        if enrich:
            rows = [_calc.enrich_bond(b) for b in rows]
        return rows

    def list_bonds_df(self, *, include_inactive: bool = False, enrich: bool = True) -> pd.DataFrame:
        return pd.DataFrame(self.list_bonds(include_inactive=include_inactive, enrich=enrich))

    def stats(self) -> dict:
        return dict(
            n_bonds=self.db.count_bonds(),
            n_with_price=self.db.count_with_price(),
            last_scrape=self.db.last_scrape_run(),
        )

    def yield_by_nation(self, **kwargs) -> list[dict]:
        return _calc.yield_by_nation(self.list_bonds(), **kwargs)

    def find_anomalies(self, **kwargs) -> list[dict]:
        return _calc.find_anomalies(self.list_bonds(), **kwargs)

    # ---- write side ------------------------------------------------------

    def refresh(self, *, headless: bool = True) -> dict:
        """Run the Selenium scrape end-to-end. Returns a summary dict.

        Requires `selenium` + `webdriver-manager` (install via the
        scraping extra: `pip install -e .[scraping]`).
        Uses the default SCRAPE_PROFILES from the bonds scraper module.
        """
        try:
            from core.data.providers._bonds_impl.scraper import run_scrape
        except ImportError as e:
            return {"status": "error", "message": f"scraping deps not available: {e}"}
        try:
            summary = run_scrape(self.db, headless=headless)
            return {"status": "ok", **(summary or {})}
        except Exception as e:
            log.exception("scrape failed")
            return {"status": "error", "message": str(e)}
