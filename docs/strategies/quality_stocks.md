# quality_stocks — long-only S&P 500 quality + momentum (ARCHIVED)

> ⚠️ **Archived as of Phase 4.** The V5 variant reached STRONGLY ROBUST 8/8 on
> in-sample walk-forward + survivorship-corrected validation, but failed the
> SPY benchmark gate (-4.6 pp/yr vs buy-and-hold over 17y). The equity sleeve
> now holds passive CSPX.L via `strategies/passive_equity/`. The full archive
> rationale lives in `_migration_log/V5_VS_SPY_DECISION.md` and the code in
> `strategies/_archived/quality_stocks/`.
>
> This document is kept for historical reference.

**Sleeve**: equity (30% of total capital, when active)
**Status**: ⚫ **ARCHIVED** — V5 was ROBUST on its own merits but lost to SPY.
**Walk-forward**: 5 folds, train 4y / test 1y, fixed params, 2016-01 → 2025-12.

## What it does

Per rebalance (monthly, first trading day):

1. Pull the current S&P 500 constituent list from FMP.
2. Exclude `Financial Services` sector.
3. Compute a quality composite per symbol: percentile-ranked ROIC + FCF yield
   + cash return + 1/debt-equity + ROIC stability (5y mean/std). Take top
   `quality_pool` (default 50).
4. From those, take the top `target_securities` (default 20) by `momentum_lookback`/`momentum_skip` momentum.
5. **Regime gate** — SPY trend filter:
   - `uptrend` (SMA(short) > SMA(long)): open new picks; engine closes dropped
     names via `manage_positions`.
   - `downtrend`: hold what's in the pick set; do NOT buy more. With
     `bond_fallback` set, allocate residual cash to that bond ETF. With
     `bond_fallback: null`, residual sits as cash within the sleeve.

Point-in-time discipline: fundamentals are filtered by `filing_date ≤
rebalance_date`, with a +90-day conservative buffer when `filingDate` is not
exposed by the FMP endpoint.

## Variants (Phase 3 refinement)

| Variant | Trend MAs | Momentum | Bond fallback | Verdict |
|---|---|---|---|---|
| **baseline** | 50/200 | 126/10 | IEF | 🔴 OVERFIT (med Sharpe -0.21) |
| V2 — faster trend | 20/100 | 126/10 | IEF | 🟡 MARGINAL (+0.91 med, but p25 negative) |
| V3 — shorter momentum | 50/200 | 60/5 | IEF | 🔴 OVERFIT (+0.01) |
| V4 — no bond fallback | 50/200 | 126/10 | null | 🟢 ROBUST (+0.64) |
| **V5 — combined** | **20/100** | **60/5** | **null** | **🟢 ROBUST (+0.745, p25 +0.480)** |

Full refinement report: `_migration_log/QUALITY_STOCKS_REFINEMENT_REPORT.md`
HTML comparison: `outputs/quality_stocks/refinement_comparison.html`

**Active variant for Phase 3 deployment: V5.** Reasoning lives in the
refinement report — short version: V5 is the most consistent (narrowest
p75-p25 spread, no fold below zero), even though V2 has a higher absolute
median.

## Config files

```
strategies/quality_stocks/config.yaml                 # baseline (still tracked, not active)
configs/quality_stocks_v2_faster_trend.yaml
configs/quality_stocks_v3_short_momentum.yaml
configs/quality_stocks_v4_no_bond_fallback.yaml
configs/quality_stocks_v5_combined.yaml               # ACTIVE
```

Pick a variant from the dropdown in `ui/pages/7_Quality_Stocks.py`, or pass
`--config configs/quality_stocks_v5_combined.yaml` to
`scripts/run_quality_walk_forward.py` / a future CLI runner.

## Implementation notes

- The `trend_short_ma`/`trend_long_ma` config keys were wired through in Phase 3
  (previously hard-coded inside `regime.is_market_uptrend`). The fix is in
  `strategies/quality_stocks/strategy.py::_trend_kwargs`.
- `bond_fallback: null` is honoured by the existing engine code:
  `self.bond_symbol = bond_symbol or self.cfg.get("bond_fallback", "IEF")` →
  `None`. The bond-allocation branch in `generate_signals` short-circuits on
  `None in history.columns` (always False), so no bond signal is emitted.
- `manage_positions` is similarly safe: `sym == self.bond_symbol` against
  `None` is False for any real symbol.

## Honesty / next validation

V5's promotion is **provisional**. The variants were chosen with prior
knowledge of the baseline's per-fold weaknesses (notably fold 3 / 2022), so
there is residual confirmation bias. Phase 4 priorities:
1. Backtest V5 on **2014-2019** (data we have but haven't used).
2. Forward paper-trade V5 in the equity sleeve at **reduced allocation** (e.g.
   20% instead of 30%) for 6-12 months before scaling to full target weight.

## Pages that use it

- **Quality Stocks** (page 7) — primary dashboard. Variant selector, run form,
  walk-forward fold table, refinement comparison table.
- **Backtest Runner** (page 3) — generic alternative entry point.
- **Portfolio Overview** (page 1, Equity tab) — pulls the most-recent backtest
  for the sleeve-value proxy.

## Files

```
strategies/quality_stocks/
├── __init__.py
├── strategy.py             # QualityStocks(Strategy)
├── factors.py              # quality composite + momentum calculators
├── regime.py               # SPY trend filter
├── runner.py               # build_panel helper for backtests
├── config.yaml             # baseline
└── tests/test_smoke.py     # 6 cases

# Variant configs (Phase 3)
configs/quality_stocks_v2_faster_trend.yaml
configs/quality_stocks_v3_short_momentum.yaml
configs/quality_stocks_v4_no_bond_fallback.yaml
configs/quality_stocks_v5_combined.yaml
```
