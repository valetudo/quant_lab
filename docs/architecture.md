# Architecture (Phase 3)

## High-level

`quant_lab` is a single-user Python monorepo for managing a multi-sleeve trading
portfolio. It combines:
- A **static strategic allocation** model (Phase 3) — sleeve weights are fixed; the
  user rebalances manually when drift exceeds a threshold.
- A **strategy-agnostic backtest engine** that drives any `Strategy` subclass
  through historical price panels.
- A **Streamlit UI** with eight pages for portfolio oversight, screening,
  backtest exploration, and operational decision support.
- A **bond-ladder tracker** that turns the legacy bonds_income strategy into a
  decision-support tool for a manually-managed ladder.

There is **no algorithmic rebalancing between sleeves**. The system signals
drift; the user trades.

## Asset allocation

Fixed 50/30/20 — bonds / equity / opportunistic — declared in
`configs/portfolio.yaml`:

| Sleeve | Target | Strategies | Notes |
|---|---:|---|---|
| bonds | 50% | bonds_income | Manual ladder. Mix 70% sovereign / 30% corporate IG. |
| equity | 30% | passive_equity | Buy-once-hold-forever VWCE.MI UCITS ETF — Vanguard FTSE All-World, ~3700 global holdings, developed + emerging, TER 0.19% (VT proxy fallback). v1.1.0 switched from CSPX (S&P 500) to address US-only bias — see `_migration_log/EQUITY_SLEEVE_GLOBAL_DECISION.md`. |
| opportunistic | 20% | pattern_finder (scaffold), reserved cash | Pattern Finder adapter ready; opportunistic slots will be wired here. |

Drift > 5pp from any sleeve target triggers a red banner on Portfolio Overview
and a list of concrete rebalance suggestions. The user executes the transfers
at the broker, then clicks "Mark as rebalanced" to add an entry to
`data_storage/portfolio/rebalance_log.jsonl`.

## Strategy interface

Every strategy subclasses `core.strategy.base.Strategy` and implements:

| Method | When called | Returns |
|---|---|---|
| `on_init(history)` | Once before main loop | None |
| `on_retrain(date, history)` | Periodic (optional) | None |
| `generate_signals(date, history, open_positions)` | Every bar | `list[Signal]` |
| `manage_positions(date, history, open_positions)` | Every bar | `list[Action]` |

Strategies operate **independently within their sleeve's capital budget**.
There is no cross-strategy communication; they share read-only data (FMP cache,
price panels) but never message each other.

## Data layer

```
┌──────────────────┐    ┌───────────────────┐    ┌─────────────────┐
│  FMP API (cloud) │ ─→ │  fmp_cache.duckdb │ ─→ │ FMPProvider     │
└──────────────────┘    │  (prices, KM,     │    │ (core/data/...) │
                        │   ratios, scrap)  │    └────────┬────────┘
                        └───────────────────┘             │
┌──────────────────┐    ┌───────────────────┐             │
│ Borsa Italiana   │ ─→ │   bonds.db        │ ─→ ┌────────▼────────┐
│ (Selenium scrap) │    │   (SQLite)        │    │   Strategy      │
└──────────────────┘    └───────────────────┘    │   (any subcls)  │
                                                  └────────┬────────┘
                        ┌───────────────────┐              │
                        │  positions.parquet│ ◀━━━━━━━━━━━━┛
                        │  (manual ladder)  │
                        └───────────────────┘
```

`data_storage/` is the local cache root. `configs/global.yaml` and the
`GDS_DB_PATH` env var override its location.

## Backtest engine

`PortfolioBacktester` (`core/backtest/engine.py`) is event-driven:

1. Check cancel-requested flag (Phase 2.5 streaming hook).
2. `manage_positions(date, ...)` → close/reduce actions.
3. `generate_signals(date, ...)` → open signals.
4. Mark-to-market and record equity.

Costs: linear bps default, sqrt-impact (Kyle's lambda) optional. Capital
liquidity is clipped proportionally — strategies can ask for more than they
have and the engine sizes down.

**Optional streaming**: pass a `StreamWriter` to `__init__` and the engine
emits JSONL events (started / equity_update / trade_open / trade_close /
completed / stopped / error) plus checks for user cancellation. This powers
the Live mode in `ui/pages/3_Backtest_Runner.py` and
`ui/pages/7_Quality_Stocks.py`. The CLI path doesn't pass a writer; behaviour
is identical to Phase 1.

## Walk-forward validation

`scripts/run_quality_walk_forward.py` runs 5 folds (train 4y / test 1y / step
1y) with **fixed** parameters across folds — no per-fold tuning. Verdict
thresholds (median OOS Sharpe):
- ≥ 0.40 with p25 > 0 → ROBUST
- ≥ 0.20 → MARGINAL
- otherwise → OVERFIT

Every active strategy must pass walk-forward before deployment.

## UI

Streamlit multi-page app, eight pages:

| # | Page | Purpose |
|---:|---|---|
| 1 | Portfolio Overview | Drift, allocation, rebalance suggestions, per-sleeve tabs |
| 2 | Strategies | Strategy registry with status badges + READMEs |
| 3 | Backtest Runner | Run any registered strategy. Live + Batch mode. |
| 4 | Data Status | Cache freshness, universe coverage |
| 5 | Bonds Screener | Filter the Borsa Italiana bond universe |
| 6 | Debug Logs | Tail the migration logs + runtime logs |
| 7 | Quality Stocks | Dedicated dashboard — variant selector, WF table, refinement comparison |
| 8 | Bond Ladder | Composition / cash flow / gaps / position management / health |

## Strategies (current status)

| Strategy | Status | Sleeve | Walk-forward |
|---|---|---|---|
| `bonds_income` | working (MVP); evolving into ladder-tracker decision support | bonds | N/A — manual decisions |
| `quality_stocks` (V5 = baseline + V2+V3+V4) | **ROBUST** (median OOS Sharpe **+0.745**, p25 **+0.480**) | equity | 5 folds, 2016-2025 |
| `quality_stocks` (baseline V1) | OVERFIT (median OOS Sharpe -0.208) — kept for reference / comparison | (deprecated) | — |
| `pair_trading_ITA` | Archived (Phase 1) — OVERFIT after 5 iter | — | see `docs/archived_strategies.md` |
| `pattern_finder` | Parked external repo | opportunistic | — |

See `docs/strategies/*.md` for per-strategy detail.

## Operational workflow

1. **Daily**: `python scripts/update_all_data.py` refreshes the FMP / bonds cache.
2. **Monthly**: open Portfolio Overview → check drift → manually rebalance if alerts → click "Mark as rebalanced".
3. **Quarterly**: re-run `scripts/run_quality_walk_forward.py --variant v5` to confirm V5 still holds out-of-sample.
4. **When a bond matures**: Bond Ladder page → gap analysis → pick a candidate from suggestions → execute at broker → add to ladder via "Add a position" form.

## Repository layout

```
core/                  Framework — data, strategy ABC, backtest, analytics, IO, execution
strategies/            Concrete strategies (bonds_income, quality_stocks, _examples)
portfolio/             Sleeve model (static_allocator + state) + _legacy/ (deprecated)
ui/                    Streamlit multi-page app + shared helpers (utils/, components/)
scripts/               CLI utilities (run_backtests, walk_forward, comparison builder, …)
configs/               YAML: global, portfolio, allocation (legacy), strategy variants
tests/                 Cross-cutting test suite
data_storage/          Local cache root — DuckDB, bonds.db, positions.parquet, audit logs
outputs/               Backtest outputs (per strategy, per window), WF verdicts, HTML reports
docs/                  Architecture notes, per-strategy docs, archived-strategy history
_backups/              Pre-migration snapshots (not under version control day-to-day)
_migration_log/        Phase reports + refactor scripts kept for traceability
```
