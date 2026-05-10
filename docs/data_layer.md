# Data layer

## Sources

### Equities — DuckDB (`global_data_storage`)

- Schema: `prices.equity_ohlcv(date, ticker, open, high, low, close, adj_close, volume, freq)`.
- Universe: `prices.universe(ticker, market, name, isin, segment, currency, sector, active)`.
- Default path: `~/.global_data_storage/store.duckdb`; override via `GDS_DB_PATH` or `configs/global.yaml`.
- Read-only access. Writes happen via the GDS ingest pipeline (separate repo).

### Bonds — SQLite (`bonds.db`)

- Tables: `bonds`, `bond_prices`, `scrape_runs`.
- Scraped by `BorsaItalianaProvider.refresh()` (Selenium, requires `[scraping]` extra).
- Default path: `<bonds_db_path>` from `configs/global.yaml`.
- Bootstrap with `scripts/migrate_bonds_db.py` (one-shot copy from the legacy `bonds/bonds.db`).

## Access pattern

```python
from quant_lab.core.data.storage import DataStorage
from quant_lab.core.data.providers.borsa_italiana_provider import BorsaItalianaProvider

storage = DataStorage.from_config()
panel = storage.load_panel(["AAPL", "MSFT"], "2024-01-01", "2024-12-31")

provider = BorsaItalianaProvider(db_path=storage.bonds_db_path)
bonds_df = provider.list_bonds_df()
```

## Provider abstraction

All providers subclass `BaseProvider` in `core/data/providers/base.py` and expose at least `provider_id` and `refresh()`. Concrete:

- `YFinanceProvider` — read-side wrapper.
- `BorsaItalianaProvider` — Selenium scrape + SQLite.
- `FMPProvider` — stub (Phase 2 for `quality_stocks` fundamentals).

## Schemas

`core/data/schemas.py` defines Pandera `DataFrameModel`s for OHLCV and bonds. Validation is **soft** in Phase 1 (returns the frame unchanged on failure) — promotable to hard in Phase 2.
