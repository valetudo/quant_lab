# Missing Docstrings — advisory only

36 public functions without docstrings. **Not blocking** for v1.0.0 — most are tiny one-liners or scripts whose names are already self-explanatory.

All modules **do** have module-level docstrings (`D100` passes cleanly).

## By area

### `core/analytics/metrics.py` (7)

- `cagr`, `annualised_vol`, `sharpe`, `sortino`, `max_drawdown`, `calmar`, `trade_stats`

Standard finance metrics — names + type hints make the contract obvious. Worth adding short docstrings before public open-source release, **not** before v1.0.0 cut.

### `core/data/` (3)

- `core/data/storage.py:30` — `load_global_config`
- `core/data/schemas.py:46` — `validate_bonds`
- `core/data/universe.py:135` — `get_universe`

### `core/io/` (3)

- `core/io/writers.py:11` — `write_json`
- `core/io/writers.py:18` — `write_csv`
- `core/io/standard_schema.py:121` — `metrics_to_standard`

### `strategies/bonds_income/positions_io.py` (1)

- line 177 (helper for writing positions parquet)

### `scripts/` (13)

CLI scripts — names are imperative and self-descriptive (`audit_constituent_history`, `verify_fmp_setup`, etc.).

### `ui/` (9)

Tiny Streamlit components and cache helpers.

## Action

Defer docstring backfill to a future "polish" pass post-v1.0.0. None of these functions are external API.
