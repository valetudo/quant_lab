# quality_stocks

**Status**: SCAFFOLD — to be implemented in Phase 2.

**Purpose**: long-only quality factor portfolio inspired by the Quantopian "Quality" factor. Will rank a US large-cap universe by composite quality score (ROIC, debt/equity, gross margin stability, accruals) and hold the top decile.

## Reference

- Original Quantopian code: see `docs/quantopian_archive/` (5 files preserved as historical reference).
- Project history and prior strategies: see `docs/archived_strategies.md`.

## Phase 2 implementation plan

1. **Data layer**: integrate `FMPProvider` (currently a stub) for fundamentals (ROIC, total debt, total equity, gross margin time series).
2. **Quality score**:
   - ROIC: NOPAT / invested capital, percentile rank cross-section.
   - Leverage: total debt / total equity, inverse-ranked.
   - Margin stability: 5y std-dev of gross margin, inverse-ranked.
   - Combine with weights from `config.yaml`.
3. **Selection**: top N (default 30) by composite score; equal-weight or score-weight.
4. **Rebalance**: quarterly with hysteresis (don't churn names whose rank moves slightly).
5. **Validation**: walk-forward against an SPY benchmark.

## TO BE IMPLEMENTED

This is a scaffold. The `Strategy` ABC methods all return empty lists — running the engine against this class produces an empty trade list (equity = initial_capital throughout). That's intentional: the framework can already be exercised end-to-end without quality logic blocking it.
