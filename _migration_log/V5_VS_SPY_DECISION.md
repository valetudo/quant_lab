# Quality Stocks V5 — Final Decision: Archive

**Date**: 2026-05-11
**Decision**: 🔴 **Archive V5. Equity sleeve becomes passive CSPX (S&P 500 UCITS ETF).**

## Verdict

After 6 phases of development and rigorous validation, Quality Stocks V5 is archived.

## Summary of validation history

| Test | Result | Outcome |
|---|---|---|
| Initial 5-fold walk-forward (Phase 3) | Median Sharpe **+0.745** | ROBUST |
| Extended 17-year walk-forward (Phase V) | Median Sharpe **+0.743** | ROBUST |
| Hold-out 2012-2019 validation | Median Sharpe **+0.739** | ROBUST |
| Bootstrap statistical significance | p ≈ 0.000 | Significant |
| Regime decomposition | 3 STRONG / 1 NEUTRAL / 1 weak | Mostly robust |
| Survivorship bias correction (Phase S) | Sharpe **+0.899** corrected | STRONGLY ROBUST (8/8) |
| **vs SPY buy-and-hold benchmark (13 y)** | **CAGR 7.83 % vs SPY 12.43 %** | **UNDERPERFORM by 4.60 pp/yr** |

## Key insight

V5 has every marker of a "robust strategy" by standard validation metrics
(Sharpe, walk-forward consistency, survivorship-corrected). But the only
metric that ultimately matters — meaningful outperformance vs the passive
index — fails.

V5 is essentially a **drawdown-smoothing strategy**: it reduces max DD from
−34 % to −12 % but at the cost of −4.6 %/yr of return. On €100k invested
2012-2024:

| | V5 | SPY buy-and-hold |
|---|---:|---:|
| CAGR | +7.83 % | +12.43 % |
| Sharpe | 0.78 | 0.79 |
| Max DD | −12.4 % | −34.1 % |
| Final equity | **€266k** | **€459k** |

V5 reduced peak drawdown by 22 pp at a cost of €193k of foregone returns
over 13 years.

## Decision rationale

Per the user's stated criterion (verbatim):

> "deve esserci una sovraperformance significativa per mettere in piedi tutto
> questo sistema, altrimenti mi compro lo spy e me lo tengo"

V5 fails this test. The equity sleeve is implemented as passive S&P 500 via
**CSPX** (iShares Core S&P 500 UCITS ETF) at **30 %** of total portfolio.

## Allocation change

| Sleeve | Before (Phase 3) | After (Phase 4) |
|---|---:|---:|
| Bonds | 60 % | **50 %** |
| Equity | 30 % | 30 % (active V5 → passive CSPX) |
| Opportunistic | 10 % | **20 %** (room for Pattern Finder + ad-hoc) |

Bonds shrinks 10 pp; opportunistic grows 10 pp. Equity weight unchanged but
its content flips from active to passive.

## Methodological lessons preserved

1. **Walk-forward integrated from the start** (lesson from pair_trading iter-5
   — never trust a one-shot backtest).
2. **Survivorship correction applied** (lesson from active equity research —
   "current S&P 500 constituents" was a 4.6 pp/yr free alpha leak).
3. **Benchmark comparison mandatory** for every active strategy (lesson from
   this decision — Sharpe and walk-forward verdicts can both be ROBUST and
   the strategy can still be inferior to its passive benchmark).
4. **Honest negative verdicts** published in the UI (lesson reinforcing all
   the above — never bury a bad result).

## Guidelines for the next active equity strategy

Before any new active equity strategy is built, require:

- **Hypothesis stated BEFORE backtest**: what edge, why now, why hasn't the
  market arbitraged it away.
- **Benchmark comparison from day 1** — pick the relevant passive baseline
  (SPY for US equity, VEUR for European equity, etc.) and design the strategy
  to *beat* it, not just to be "robust".
- **Explicit decision rule written before seeing results**: "promote if
  CAGR vs benchmark > +2 pp AND Sharpe delta > +0.15; archive otherwise".
- **Resist the salvage iteration cycle**: when a strategy fails the
  benchmark test, archive it. Do not try to "fix" it with more parameter
  tweaks — that's the same selection-bias loop that produced V5.
- **Workflow** for an active equity strategy:
  1. Hypothesis paper (~1 page) before code
  2. Implementation
  3. Walk-forward (5+ folds, fixed parameters)
  4. Survivorship correction if equity-based
  5. Bootstrap CI
  6. **Benchmark comparison — the gate**
  7. Paper trading 6+ months
  8. Live capital only after step 7 confirms

## Files preserved

- `strategies/_archived/quality_stocks/` — full source (preserved, not deleted)
- `_migration_log/PHASE2_REPORT.md`, `PHASE3_REPORT.md`, `PHASE2_5_REPORT.md`
- `_migration_log/QUALITY_STOCKS_REFINEMENT_REPORT.md` — V5 selection rationale
- `_migration_log/V5_FULL_VALIDATION_REPORT.md` — 17 y validation
- `_migration_log/V5_SURVIVORSHIP_VALIDATION_REPORT.md` — survivorship test
- `outputs/quality_stocks/walkforward_*` — all walk-forward outputs
- `outputs/quality_stocks/v5_vs_spy_definitive.html` — definitive comparison
- `outputs/quality_stocks/survivorship_comparison.html` — survivorship overlay

These are the receipts: the decision is justifiable, reproducible, and
preserved for future reference.
