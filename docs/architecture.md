# Architecture

## Overview

`quant_lab` is a strategy-agnostic framework with a clean separation between:
- **core**: data access, strategy interface, backtest engine, analytics, IO, execution.
- **strategies**: concrete strategy implementations (one subpackage each).
- **portfolio**: cross-strategy aggregation and allocation (Phase 2).
- **ui**: Streamlit multi-page app over the framework.

## Strategy interface

Every strategy subclasses `quant_lab.core.strategy.base.Strategy` and implements:

| Method | When called | Returns |
|--------|-------------|---------|
| `on_init(history)` | Once before main loop | None |
| `on_retrain(date, history)` | Periodic (optional override) | None |
| `generate_signals(date, history, open_positions)` | Every bar | `list[Signal]` |
| `manage_positions(date, history, open_positions)` | Every bar | `list[Action]` |

Strategies emit `Signal` (open) and `Action` (close/reduce) — the engine handles the rest.

## Data layer

- **Prices**: read from `global_data_storage` DuckDB (`prices.equity_ohlcv`) via `core/data/storage.py`.
- **Bonds**: SQLite at `<bonds_db_path>` populated by `BorsaItalianaProvider`.
- **Universe**: static lists in `core/data/universe.py` for testing; live universe in `prices.universe`.

## Engine

`PortfolioBacktester` (in `core/backtest/engine.py`) is the event loop:

1. `manage_positions(date, history, open)` → close/reduce actions.
2. `generate_signals(date, history, open)` → open signals.
3. Mark-to-market and record equity.

Costs: linear bps or sqrt-volume Kyle impact, configurable.

## Outputs

Each backtest writes three files into `outputs/<strategy>/<window>/`:
- `trades_std.csv` — per-trade log (STANDARD_TRADE_COLUMNS).
- `equity_std.csv` — per-day equity (STANDARD_EQUITY_COLUMNS).
- `metrics_std.json` — performance summary (STANDARD_METRICS_KEYS).

This schema is uniform across strategies so the portfolio aggregator can read N strategies in one pass.
