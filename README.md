# quant_lab

Quantitative trading monorepo: strategies, backtest engine, screener, and Streamlit UI.

## Layout

```
core/             Framework: data, strategy ABC, backtest, analytics, IO, execution
strategies/       Concrete strategies (bonds_income working, quality_stocks scaffold)
portfolio/        Multi-strategy aggregation (scaffold)
ui/               Streamlit multi-page app
scripts/          CLI utilities (run_backtests, update_all_data, migrate_bonds_db)
configs/          Global YAML configuration
tests/            Cross-cutting test suite
docs/             Architecture notes, history of archived strategies
```

## Quick start

```bash
# from trading_systems/quant_lab
python -m venv .venv
.venv\Scripts\activate           # Windows
pip install -r requirements.txt

# one-time: migrate the bonds.db into the configured location
python scripts/migrate_bonds_db.py

# run tests
pytest tests/ -ra

# run a backtest from CLI
python scripts/run_backtests.py --strategy dummy_buy_and_hold \
    --start 2023-01-02 --end 2023-12-29

# launch the UI
streamlit run ui/main.py
```

## Configuration

`configs/global.yaml` controls paths to the DuckDB store (`global_data_storage`) and the bonds SQLite DB. Override with env vars:
- `GDS_DB_PATH` — path to the DuckDB store.

## Strategies

| Strategy | Status | Description |
|----------|--------|-------------|
| `bonds_income` | working (MVP) | Monthly-rebalanced buy-and-hold sovereign bond income |
| `quality_stocks` | scaffold | Quantopian-style quality factor (Phase 2) |
| `dummy_buy_and_hold` | reference | "Hello World" template (in `strategies/_examples/`) |

## Adding a strategy

Subclass `quant_lab.core.strategy.base.Strategy`. See `docs/adding_a_strategy.md` for the walkthrough. The reference implementation lives in `strategies/_examples/dummy_buy_and_hold.py`.

## Git remote

This repository is initialized locally. To push to a remote:

```bash
git remote add origin <url>
git push -u origin main
```

## History

- **Phase 1** (2026-05): monorepo scaffolding from `pair_trading_ITA` + `bonds`.
- See `docs/archived_strategies.md` for the project history and reasons behind archiving `pair_trading_ITA`.

## License

MIT.
