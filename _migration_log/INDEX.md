# Migration Log Index

Chronological project history. Each report captures the state and reasoning at the end of a development phase. **Read in order if you're trying to understand why the system looks the way it does.**

## Phase 1 — Initial monorepo scaffolding
- **`PHASE1_REPORT.md`** — Initial scaffolding from `pair_trading_ITA` + `bonds` legacy projects. Established the core layout: `core/`, `strategies/`, `portfolio/`, `ui/`, `scripts/`, `tests/`. Set up FTSE MIB universe seeding from Wikipedia, segmented FTSE optgroups, dashboard skeleton.

## Phase 2 — FMP integration + first active strategy
- **`PHASE2_REPORT.md`** — FMP Premium integration, DuckDB cache, Quality Stocks v1 (baseline). Walk-forward 5-fold returned 🔴 OVERFIT (median OOS Sharpe −0.208). Honest negative result delivered.
- **`PHASE2_FIX_REPORT.md`** — Import-inconsistency fix: 44 files switched from `from quant_lab.X import Y` to `from X import Y` (no `pip install -e .`). `conftest.py` adjusted; 9 script bootstraps rewritten.
- **`PHASE2_5_REPORT.md`** — UI polish: Bonds Screener filters, live equity streaming in Backtest Runner (Quantopian-style), Stop button with selection-bias disclaimer.

## Phase 3 — Static allocation + Bond Ladder + Quality Stocks refinement
- **`PHASE3_REPORT.md`** — Static strategic allocation 60/30/10, Portfolio Overview page, Bond Ladder designer with cash flow projection + gap analysis + health check. 29 new tests.
- **`QUALITY_STOCKS_REFINEMENT_REPORT.md`** — V1→V5 parameter exploration. V5 (faster trend + shorter momentum + no bond fallback) chosen as the best-of-five with honest documentation of confirmation-bias risk.

## Phase V — Full 17-year validation
- **`V5_FULL_VALIDATION_REPORT.md`** — Walk-forward extended to 13 folds 2009-2025, hold-out 2012-2019, bootstrap CI [+0.22, +1.30] excludes 0. 5/5 decision tests passed. V5 declared STRONGLY ROBUST.

## Phase S — Survivorship correction
- **`V5_SURVIVORSHIP_VALIDATION_REPORT.md`** — Historical S&P 500 constituents (1518 events) reconstructed point-in-time. V5 re-validated with corrected universe; survivorship-corrected median Sharpe **+0.899** (vs +0.743 uncorrected). 8/8 tests passed. V5 confirmed STRONGLY ROBUST.

## Phase B — Benchmark + UX polish
- (Benchmark vs SPY comparison run, no standalone report. Findings landed in **`V5_VS_SPY_DECISION.md`**.) Key result: V5 vs SPY buy-and-hold on 13-y OOS — V5 CAGR +7.83 % vs SPY +12.43 %, V5 underperforms by **−4.60 pp/yr**. Sharpe essentially tied (0.78 vs 0.79); V5 Max DD better (−12 % vs −34 %). Verdict: V5 is a drawdown smoother, NOT alpha.

## Phase 4 — Final restructure + Quality Stocks archive
- **`V5_VS_SPY_DECISION.md`** — Definitive decision report: V5 archived after failing the benchmark gate. Allocation flipped from 60/30/10 to 50/30/20 (more capital to opportunistic), equity sleeve becomes passive (CSPX UCITS), pattern_finder adapter scaffolded for future.

## Reference scripts archived alongside
- `_phase2_fix_bootstraps.py` + `_phase2_fix_refactor.py` — one-shot import-fix helpers from Phase 2 fix. Kept for traceability.
- `phase*_step_*.log` + `step_*.log` — chronological build logs from Phase 1-2.
- `phase2_fix_20260511_091740.log` — full record of the 120 import-rewrite substitutions.

## Reading order for a new contributor

1. **README.md** (project root) — current state, quick start.
2. **PHASE4_REPORT.md** is intentionally not present — Phase 4 deliverables are documented across **V5_VS_SPY_DECISION.md** + the per-strategy READMEs (`strategies/passive_equity/README.md`, `strategies/pattern_finder/README.md`) + the architecture doc (`docs/architecture.md`).
3. **V5_VS_SPY_DECISION.md** — to understand why the equity sleeve is passive.
4. **docs/adding_a_strategy.md** — to add new strategies.

The chronological reports (PHASE1 → V5_VS_SPY_DECISION) are the historical *receipts*; the architecture doc + decision report are the live *contract*.
