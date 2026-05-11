# bonds_income — sovereign + corporate bond ladder

**Sleeve**: bonds (50% of total capital)
**Mode**: Hybrid — algorithmic backtest *and* live ladder decision support.
**Walk-forward**: N/A — the live mode is manual.

## What it does

`bonds_income` exists in two forms inside the same package:

1. **Backtest strategy** (`strategy.py`) — monthly ranking by net yield, top-N
   selection from a snapshot of the Borsa Italiana bond universe.
   Engine-compatible. Used by the walk-forward harness and CLI runs.

2. **Live ladder tracker** (`ladder.py` + `positions_io.py`) — manages a
   manually-built bond ladder. Tracks current positions, identifies bucket
   gaps vs a target structure, projects cash flows, and ranks screener
   candidates for filling gaps.

The two coexist because the **production flow is manual**: the user buys
individual bonds at the broker and updates the ladder via the UI. The
backtest strategy is kept for back-compat with the engine and for
hypothetical full-automation later.

## Live ladder defaults (Phase 3)

Recorded in `LadderConfig.__init__`:

| Parameter | Default | Notes |
|---|---|---|
| `maturity_buckets_years` | 1..10 | rolling 1-10y equi-weighted |
| `sovereign_weight` | 0.70 | 70% sovereign |
| `corporate_weight` | 0.30 | 30% corporate |
| `min_rating_corporate` | BBB- | investment grade only |
| `max_issuer_concentration_pct` | 5.0 | max 5% of ladder in one corporate issuer |
| `liquidity_reserve_pct` | 5.0 | 5% in cash or <1y bonds |

All four can be re-tuned from the UI sidebar without editing code.

## Position schema

One row per position, both active and historical. Schema in
`POSITION_COLUMNS` (`strategies/bonds_income/positions_io.py`). Lives at
`data_storage/bonds/positions.parquet`. Every write produces a backup at
`positions_backup_<UTC-isoformat>.parquet`.

## Cash-flow projection — caveat

**MOCK assumption**: annual coupon on the anniversary of `maturity_date`.
Many corporates pay semi-annually; some Treasury bonds pay semi-annually. The
projection over-counts coupons for those (one payment vs the real two per
year, but full-year amount) — it understates payment density, not magnitude.

When the real coupon-schedule data feed is wired in (Phase 4 TODO), the
projection logic in `LadderTracker.get_cash_flow_projection()` will be
swapped out. The interface stays the same.

## Backtest strategy — not the production flow

The backtest path uses a flat synthetic panel (par=100 for every ISIN) because
we don't yet have historical bond prices. The walk-forward harness does not
run on bonds_income for the same reason. Phase 4 priority: BTP/OAT historical
price panel.

## Pages that use it

- **Bond Ladder** (page 8) — primary interface. Composition, gaps, cash flow,
  position manager, health check.
- **Portfolio Overview** (page 1, Bonds tab) — reads `positions.parquet` to
  compute the sleeve value used in drift analysis.
- **Bonds Screener** (page 5) — filters the same `BorsaItalianaProvider`
  data the ladder tracker pulls candidates from.

## Files

```
strategies/bonds_income/
├── __init__.py
├── strategy.py              # backtest engine adapter (legacy MVP)
├── selection.py             # enrich_and_select used by both modes
├── ladder.py                # LadderConfig, LadderTracker
├── positions_io.py          # parquet persistence + backups
├── config.yaml              # backtest parameters
├── README.md
└── tests/test_smoke.py
```

Tests live additionally at `tests/test_ladder.py` (15 cases).
