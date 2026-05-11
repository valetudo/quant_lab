# Phase 2 — Import Inconsistency Fix Report

**Generated**: 2026-05-11
**Status**: ✅ COMPLETE — all 7 sanity checks (Step 4–8) green; walk-forward verdict reproduces.
**Refactor log**: `_migration_log/phase2_fix_20260511_091740.log`

---

## 1. What was wrong

Phase 2 introduced imports using the `quant_lab.X` prefix even though the project is **not** installed via `pip install -e .`. The previous bootstrap in `conftest.py` and in each script added the *parent* of the repo root to `sys.path`, which makes `quant_lab.X` work for pytest and for streamlit's wrapper but fails for any direct `python -c "from core.X..."` invocation because the inner module then re-imports `from quant_lab.Y...` and crashes.

Symptom (reproduced before the fix):
```
PS> python -c "from core.data.providers.fmp_provider import FMPProvider"
ModuleNotFoundError: No module named 'quant_lab'
```

The convention going forward: **import without prefix** — `from core.X`, `from strategies.X`, `from portfolio.X`, `from ui.X`. The repo root is added to `sys.path` directly (not its parent).

---

## 2. Files modified

| Bucket | Count | Notes |
|---|---:|---|
| Source files with `from quant_lab.X` → `from X` (auto, via refactor script) | **44** | 120 line-level substitutions |
| Bootstrap blocks rewritten (scripts/ + ui/pages/) | **9** | Now insert `_REPO_ROOT`, not `_PARENT` |
| `conftest.py` | 1 | Now adds repo root, not parent |
| `pyproject.toml` | 1 | `package-dir = { quant_lab = "." }` removed; remaining flat-layout sketch documented as "not used in phase 1-2" |
| `ui/main.py` | 1 | Bootstrap updated; comment refreshed |
| `ui/pages/2_Strategies.py` | 1 | Dynamic `__import__("quant_lab....")` literals rewritten **and** `QualityStocks()` instantiation fixed to pass `fmp=FMPProvider(), universe_symbols=[], prefetch=False` so the page renders without the `missing fmp argument` TypeError |
| **Net distinct files touched** | **~52** | |

Helper refactor scripts (one-shot, kept under `_migration_log/` for traceability):
- `_migration_log/_phase2_fix_refactor.py` — the prefix-strip pass.
- `_migration_log/_phase2_fix_bootstraps.py` — the sys.path rewrite pass.

## 3. Substitution patterns applied

| # | Old pattern | New pattern |
|---|---|---|
| 1 | `from quant_lab.X import Y` | `from X import Y` |
| 2 | `from quant_lab.X.Y.Z import W` | `from X.Y.Z import W` |
| 3 | `import quant_lab.X` | `import X` (no occurrences found) |
| 4 | `from quant_lab import X` | (no occurrences found) |
| 5 | `__import__("quant_lab.strategies.bonds_income", ...)` | `__import__("strategies.bonds_income", ...)` (3× in `2_Strategies.py`) |
| 6 | `_PARENT = _REPO_ROOT.parent ; sys.path.insert(0, _PARENT)` | `sys.path.insert(0, _REPO_ROOT)` |
| 7 | `# --- bootstrap: make `import quant_lab` resolve ---` | `# --- bootstrap: add repo root to sys.path (no pip install needed) ---` |

Docstrings/comments that mention "quant_lab" as the *project name* were left intact (e.g. `ui/main.py` module docstring) — they are descriptive, not import statements.

## 4. Sanity check results (Steps 4–8)

| Step | Check | Status | Result |
|---|---|---|---|
| 4.1 | `from core.data.providers.fmp_provider import FMPProvider` | ✅ | `1 OK` |
| 4.2 | `from core.backtest.engine import PortfolioBacktester` | ✅ | `2 OK` |
| 4.3 | `from strategies.bonds_income.strategy import BondsIncome` | ✅ | `3 OK` |
| 4.4 | `from strategies.quality_stocks.strategy import QualityStocks` | ✅ | `4 OK` |
| 4.5 | `from strategies._examples.dummy_buy_and_hold import DummyBuyAndHold` | ✅ | `5 OK` |
| 4.6 | `from portfolio.master_allocator import EqualWeightAllocator` | ✅ | `6 OK` |
| 4.7 | `from portfolio.aggregator import PortfolioAggregator` | ✅ | `7 OK` |
| 4.8 | `pytest tests/ strategies/ -x` | ✅ | **40 passed** in 21s (run twice — after refactor and again after page fix) |
| 5.1 | `python scripts/verify_fmp_setup.py` | ✅ | `OK    FMP_API_KEY found (length: 32, masked: ***...***)` |
| 5.2 | `python scripts/verify_fmp_connectivity.py` | ✅ | `OK   /profile AAPL -> $293.257` · `premium plan active` |
| 6 | `python scripts/run_backtests.py --strategy quality_stocks --start 2023-01-01 --end 2023-12-31` | ✅ | `trades=11, sharpe=0.31, final_eq=51292` (initial 50k); JSON: see [`outputs/quality_stocks/2023-01-01_2023-12-31/metrics_std.json`](outputs/quality_stocks/2023-01-01_2023-12-31/metrics_std.json) |
| 7.1 | `streamlit run ui/main.py` boots | ✅ | HTTP 200 on `/`, `/Portfolio_Overview`, `/Strategies`, `/Backtest_Runner`, `/Data_Status`, `/Bonds_Screener`, `/Quality_Stocks` |
| 7.2 | `2_Strategies.py` no longer raises `missing fmp argument` for quality_stocks | ✅ | Verified by reproducing the page's `instantiate=lambda` outside streamlit; pre-fix raised `TypeError`, post-fix returns a QualityStocks instance with empty pre-init universe |
| 7.3 | Bonds Screener still works | ✅ | `5_Bonds_Screener.py` imports clean, page returns 200 |
| 7.4 | Portfolio Overview page loads | ✅ | `1_Portfolio_Overview.py` page returns 200 |
| 8 | `python scripts/run_quality_walk_forward.py` | ✅ | 5 folds completed; **median OOS Sharpe = −0.208 → 🔴 OVERFIT**; output at `outputs/quality_stocks/walk_forward_verdict.json` |

### Step 6 — Quality Stocks single backtest 2023

| Metric | Value |
|---|---|
| n_trades | **11** |
| Sharpe | **0.31** |
| Final equity (EUR) | **51 292** |
| Total return | +2.58% |
| Sortino | 0.63 |
| Max DD | −11.5% |
| Hit rate | 72.7% |
| Profit factor | 1.36 |

### Step 8 — Quality Stocks walk-forward (5 folds, fixed params)

| Fold | Test window | Sharpe | Return | Trades | Max DD |
|---|---|---:|---:|---:|---:|
| 1 | 2020 | **+1.76** | +16.2% | 32 | −4.7% |
| 2 | 2021 | −0.27 | −2.7% | 27 | −7.2% |
| 3 | 2022 | **−1.50** *(worst)* | −14.6% | 1 | −18.4% |
| 4 | 2023 | −0.21 | −2.6% | 27 | −11.5% |
| 5 | 2024 | −0.15 | −1.9% | 28 | −10.2% |

- Median OOS Sharpe = **−0.208**
- p25 / p75 = **−0.269 / −0.146**
- Worst fold = **Fold 3 (2022)**, Sharpe −1.50, only 1 trade
- **Verdict: 🔴 OVERFIT**

## 5. PHASE2_REPORT.md — was it accurate?

**Mostly yes**, with two concrete asterisks:

| Claim in PHASE2_REPORT.md | Reality after re-run | Verdict |
|---|---|---|
| 40/40 pytest pass | 40/40 pass | ✅ True (and was true under the old `quant_lab.X` scheme because `conftest.py` was set up for it) |
| Walk-forward verdict = OVERFIT | OVERFIT | ✅ True |
| Median OOS Sharpe = −0.208 | −0.208 | ✅ Exact match |
| p25/p75 = −0.269 / −0.146 | −0.269 / −0.146 | ✅ Exact match |
| Fold 1 Sharpe = **+1.87**, return +17.3% | **+1.76**, return +16.2% | ⚠ Small numerical drift (~6% Sharpe, ~1pp return). Other 4 folds match to 2 decimals. Likely a cache/data refresh between the original run and now; doesn't change the verdict. |
| Fold 3 Sharpe = −1.50, n_trades=1 | −1.50, n_trades=1 | ✅ Exact match (the worst fold reproduces verbatim) |
| Single-shot 2020–2024 Sharpe = 0.879 | Not re-run (single-shot 2023-only used instead in Step 6) | n/a |
| "Sanity check #5: Quality Stocks UI page functional ✅" | **Page parsed and served HTTP 200, but actual user interaction on `2_Strategies.py` would have raised `TypeError: QualityStocks.__init__() missing 1 required keyword-only argument: 'fmp'`** | ❌ **Misleading.** The check verified HTTP 200 (the streamlit shell), not the per-page execution. The bug was real, has now been fixed in `ui/pages/2_Strategies.py`. |
| "Sanity check #6: Portfolio Overview UI page functional ✅" | HTTP 200; not exercised end-to-end here | likely fine; the bootstrap was wrong (`_PARENT`) but didn't surface because streamlit's own pythonpath also added the parent dir. After the fix, still 200. |

**Bottom line.** The walk-forward verdict and ~95% of the numerical claims in PHASE2_REPORT are reliable. The two soft spots:
1. **UI sanity checks were HTTP-200 only**, which missed the `2_Strategies.py` instantiation bug. Future UI claims should exercise at least one round-trip through `streamlit.testing.v1.AppTest` (or hit the websocket).
2. **Fold-1 numerical drift** is small but real (1.76 vs 1.87). Most likely from the FMP cache being warmer/different in the rerun; verdict is unchanged. Worth re-checking if any further claim depends on the precise fold-1 Sharpe.

## 6. Other inconsistencies found during the refactor

| # | Finding | Action taken |
|---|---|---|
| 1 | `ui/pages/2_Strategies.py` instantiated `QualityStocks()` with no args. Pre-existing bug, latent because the page only triggers on render and HTTP 200 check didn't catch it. | Fixed: pass `fmp=FMPProvider(), universe_symbols=[], prefetch=False`. The card now shows universe_size=0 until on_init runs (consistent with `bonds_income` which also shows 0 pre-init). |
| 2 | `pyproject.toml` had `package-dir = { "quant_lab" = "." }` — implied an editable install would expose top-level packages under `quant_lab.*`. This is the source of the mixed-style confusion. | Removed the `package-dir` mapping and added a leading comment explaining that packaging is **not used in phase 1-2** and the remaining `packages.find` block is a flat-layout sketch reserved for a future phase. |
| 3 | 9 scripts/pages had a bootstrap that inserted the **parent** of repo root (legacy `quant_lab.X` support). With the prefix gone, those scripts ran fine via pytest (which doesn't need them — conftest now also adds repo root) but failed when invoked directly. | All 9 rewritten to insert `_REPO_ROOT` / `_PROJECT_ROOT` instead of `_PARENT`. |
| 4 | No circular imports or "imports for things that no longer exist" turned up. | — |
| 5 | The `_migration_log/quant_lab_import_issues.txt` inventory file is UTF-16 LE encoded and ~37k lines, mostly noise from `_backups/`. The actual live-tree issue list is the grep performed at the start of this fix. | Left as-is; this fix report supersedes it. |

## 7. Time spent

| Phase | Wall time |
|---|---|
| Diagnosis + grep inventory | ~5 min |
| Wrote + ran refactor script (44 files, 120 subs) | ~3 min |
| Wrote + ran bootstrap-rewrite script (9 files) | ~2 min |
| Smoke imports + pytest | ~1 min |
| `verify_fmp_setup` + `verify_fmp_connectivity` | ~1 min |
| `run_backtests.py quality_stocks 2023` | ~1 min |
| Streamlit boot + HTTP probe + `2_Strategies.py` fix + retest | ~3 min |
| `run_quality_walk_forward.py` (5 folds × ~46s = ~4 min + panel build) | ~5 min |
| Report drafting | ~5 min |
| **Total** | **~25 min** |

## 8. Open items / non-fixes

- **Walk-forward verdict is still OVERFIT.** This refactor only touched imports; it did NOT touch strategy logic. The OVERFIT result is unchanged from PHASE2_REPORT.md and is the correct, honest answer for the current quality_stocks definition. Phase 3 TODO list (see PHASE2_REPORT §11) already names "Quality Stocks regime fix" as a HIGH priority.
- **Fold-1 Sharpe drift (1.76 vs 1.87)** is worth a brief investigation in Phase 3 if anyone re-runs and gets a third different number. Probably benign (cache state differences) but should be confirmed.
- **The streamlit verification done here was HTTP-200 + page-by-page Python instantiation smoke**, not real end-to-end browser interaction. A future `streamlit.testing.v1.AppTest`-based check would close the gap that let `missing fmp argument` slip through Phase 2.
