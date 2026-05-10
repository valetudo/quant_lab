# ui

**Status**: working

**Purpose**: Streamlit multi-page app for navigating quant_lab — strategies, backtests, data status, bonds screener, logs.

## Run

```bash
streamlit run ui/main.py
```

## Pages

| Page | Status | What it does |
|------|--------|--------------|
| Portfolio Overview | stub | Phase-2 aggregate view |
| Strategies | working | List + drill-down with README inline |
| Backtest Runner | working | Pick strategy, run engine, view metrics + equity curve, persist to outputs/ |
| Data Status | working | DuckDB universe + ticker coverage |
| Bonds Screener | working | Borsa Italiana screener with filters + Plotly chart |
| Debug Logs | working | Browse `_migration_log/` and `logs/` with level filtering |

## Pages are intentionally NOT in `__init__.py`-importable form

Streamlit auto-discovers `pages/*.py` and serves them in the sidebar. The leading numeric prefix controls ordering.
