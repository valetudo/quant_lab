# Quality Stocks (Archived 2026-05-11)

**Reason**: Underperformed SPY buy-and-hold by **-4.60 pp/yr** in a 13-year OOS
comparison (2012-01 → 2025-01).

V5 (combined: trend MA 20/100 + momentum 60/5 + no bond fallback) passed every
classical robustness test:

- 8/8 decision-matrix tests (Phase V + Phase S)
- Survivorship-corrected median OOS Sharpe **+0.899**
- Hold-out 2012-2019 (no Phase-3 selection data): median Sharpe **+0.739** —
  matches full history exactly
- Bootstrap 95% CI **[+0.22, +1.30]** excludes 0, p≈0.000

But the only metric that ultimately matters — meaningful outperformance vs a
passive benchmark — failed:

| | V5 | SPY buy-and-hold |
|---|---:|---:|
| CAGR (2012-2025) | +7.83% | +12.43% |
| Sharpe | 0.78 | 0.79 |
| Max DD | -12.4% | -34.1% |
| Final equity (€100k initial) | €266k | €459k |

V5 is essentially a "drawdown smoothing" strategy: -22pp drawdown reduction in
exchange for -4.6 pp/yr foregone returns. Per the user's stated criterion
("deve esserci una sovraperformance significativa per mettere in piedi tutto
questo sistema, altrimenti mi compro lo spy e me lo tengo"), V5 fails.

## Decision report

Full reasoning, lessons learned, future guidelines:
`_migration_log/V5_VS_SPY_DECISION.md`

## Code preserved here for reference

To re-enable (not recommended without a new hypothesis):
1. Move folder back: `git mv strategies/_archived/quality_stocks strategies/quality_stocks`
2. Re-register in `configs/portfolio.yaml` equity sleeve
3. Restore `ui/pages/7_Quality_Stocks.py` from `ui/_archived/`
4. Update `tests/test_strategy_interface.py` import

## Reports archived

- `_migration_log/PHASE2_REPORT.md` — initial QS development
- `_migration_log/QUALITY_STOCKS_REFINEMENT_REPORT.md` — V5 selection
- `_migration_log/V5_FULL_VALIDATION_REPORT.md` — 17y validation
- `_migration_log/V5_SURVIVORSHIP_VALIDATION_REPORT.md` — survivorship test
- `outputs/quality_stocks/v5_vs_spy_definitive.html` — definitive comparison
- `outputs/quality_stocks/survivorship_comparison.html` — survivorship analysis
- `_migration_log/V5_VS_SPY_DECISION.md` — this archive decision
