"""DataStorage — single entry point to read/write market data.

For prices: thin wrapper around the global_data_storage DuckDB store.
For bonds: SQLite at <data_storage_path>/bonds/bonds.db (Borsa Italiana scrape).

Configuration comes from `configs/global.yaml` (default path) or via the
GDS_DB_PATH / bonds_db_path env vars.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional, Sequence

import pandas as pd
import yaml

log = logging.getLogger(__name__)


def _project_root() -> Path:
    """quant_lab/ directory — two levels above this file."""
    return Path(__file__).resolve().parents[2]


def load_global_config(path: Optional[Path] = None) -> dict:
    p = Path(path) if path else (_project_root() / "configs" / "global.yaml")
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _default_duckdb_path(cfg: dict) -> Path:
    env = os.environ.get("GDS_DB_PATH")
    if env:
        return Path(env)
    cfg_path = cfg.get("duckdb_path")
    if cfg_path:
        return Path(cfg_path)
    return Path.home() / ".global_data_storage" / "store.duckdb"


@dataclass
class DataStorage:
    duckdb_path: Path
    bonds_db_path: Path
    data_storage_path: Path

    @classmethod
    def from_config(cls, cfg: dict | None = None) -> "DataStorage":
        cfg = cfg or load_global_config()
        return cls(
            duckdb_path=_default_duckdb_path(cfg),
            bonds_db_path=Path(cfg.get("bonds_db_path") or
                               (_project_root() / "data_storage" / "bonds" / "bonds.db")),
            data_storage_path=Path(cfg.get("data_storage_path") or
                                    (_project_root() / "data_storage")),
        )

    # ---- equity price panel (DuckDB) -------------------------------------

    def load_panel(
        self,
        tickers: Sequence[str],
        start: date | str,
        end: date | str,
        *,
        field: str = "adj_close",
    ) -> pd.DataFrame:
        """Wide DataFrame [date × ticker] of `field` (default adj_close)."""
        if not tickers:
            return pd.DataFrame()
        if field not in {"open", "high", "low", "close", "adj_close", "volume"}:
            raise ValueError(f"unsupported field: {field!r}")
        if not self.duckdb_path.exists():
            log.warning("DuckDB store not found at %s — returning empty panel", self.duckdb_path)
            return pd.DataFrame()

        import duckdb  # local import so the bonds-only path doesn't require it
        placeholders = ",".join("?" for _ in tickers)
        sql = f"""
            SELECT date, ticker, {field} AS value
            FROM prices.equity_ohlcv
            WHERE freq = '1d'
              AND ticker IN ({placeholders})
              AND date BETWEEN ? AND ?
            ORDER BY date, ticker
        """
        with duckdb.connect(str(self.duckdb_path), read_only=True) as con:
            long = con.execute(sql, [*tickers, start, end]).fetchdf()

        if long.empty:
            return pd.DataFrame(index=pd.DatetimeIndex([], name="date"))
        wide = long.pivot(index="date", columns="ticker", values="value")
        wide.index = pd.to_datetime(wide.index)
        wide.index.name = "date"
        cols = [t for t in tickers if t in wide.columns]
        return wide[cols]

    def load_universe_meta(self) -> pd.DataFrame:
        """Return prices.universe rows (active only)."""
        if not self.duckdb_path.exists():
            return pd.DataFrame()
        import duckdb
        with duckdb.connect(str(self.duckdb_path), read_only=True) as con:
            try:
                df = con.execute(
                    """
                    SELECT ticker, market, name, isin, segment, currency, sector
                    FROM prices.universe
                    WHERE active = TRUE
                    ORDER BY ticker
                    """
                ).fetchdf()
            except Exception as e:
                log.warning("universe meta unavailable: %s", e)
                df = pd.DataFrame()
        return df

    def list_known_tickers(self) -> list[str]:
        if not self.duckdb_path.exists():
            return []
        import duckdb
        with duckdb.connect(str(self.duckdb_path), read_only=True) as con:
            try:
                df = con.execute(
                    "SELECT DISTINCT ticker FROM prices.equity_ohlcv ORDER BY ticker"
                ).fetchdf()
                return df["ticker"].astype(str).tolist()
            except Exception:
                return []

    # ---- bonds DB --------------------------------------------------------

    def bonds_db_exists(self) -> bool:
        return self.bonds_db_path.exists()

    # ---- FMP parquet tree (Phase 2) -------------------------------------

    @property
    def prices_root(self) -> Path:
        return self.data_storage_path / "prices"

    def list_universes(self) -> list[str]:
        """List universes available on disk (post-FMP migration)."""
        root = self.prices_root
        if not root.exists():
            return []
        out = []
        for country in sorted(root.iterdir()):
            if country.is_dir():
                # ETF/indices are flat; sp500/ftse100 live under country/
                if country.name in {"etf", "indices"}:
                    if any(country.glob("*.parquet")):
                        out.append(country.name)
                else:
                    for univ in sorted(country.iterdir()):
                        if univ.is_dir() and any(univ.glob("*.parquet")):
                            out.append(f"{country.name}/{univ.name}")
        return out

    def _universe_dir(self, universe: str) -> Path:
        return self.prices_root / universe

    def get_universe_symbols(self, universe: str) -> list[str]:
        d = self._universe_dir(universe)
        if not d.exists():
            return []
        # Filename -> symbol (reverse the safe-symbol mapping)
        out = []
        for p in sorted(d.glob("*.parquet")):
            stem = p.stem
            sym = stem.replace("_idx_", "^")
            # Common LSE suffix encoding "BARC_L" -> "BARC.L"
            if "_" in sym and sym.endswith("_L"):
                sym = sym[:-2] + ".L"
            out.append(sym)
        return out

    def _safe_symbol(self, symbol: str) -> str:
        return symbol.replace("^", "_idx_").replace("/", "_").replace(".", "_")

    def get_prices(
        self,
        symbol: str,
        start: date | str | None = None,
        end: date | str | None = None,
        *,
        universe: Optional[str] = None,
    ) -> pd.DataFrame:
        """Read OHLCV from the parquet tree.

        If `universe` is given, looks directly at that universe's dir.
        Otherwise, searches all universes for a matching parquet file.
        """
        candidates = (
            [self._universe_dir(universe)] if universe else
            [self._universe_dir(u) for u in self.list_universes()]
        )
        safe = self._safe_symbol(symbol)
        for d in candidates:
            p = d / f"{safe}.parquet"
            if p.exists():
                df = pd.read_parquet(p)
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").set_index("date")
                if start:
                    df = df[df.index >= pd.to_datetime(start)]
                if end:
                    df = df[df.index <= pd.to_datetime(end)]
                return df
        return pd.DataFrame()

    def get_prices_panel(
        self,
        symbols: Sequence[str],
        start: date | str | None = None,
        end: date | str | None = None,
        *,
        universe: Optional[str] = None,
        field: str = "adj_close",
    ) -> pd.DataFrame:
        """Wide DataFrame [date × symbol] of `field`. Skips missing symbols silently."""
        frames = {}
        for s in symbols:
            df = self.get_prices(s, start, end, universe=universe)
            if df.empty or field not in df.columns:
                continue
            frames[s] = df[field]
        if not frames:
            return pd.DataFrame()
        out = pd.concat(frames, axis=1)
        out.columns.name = "symbol"
        return out
