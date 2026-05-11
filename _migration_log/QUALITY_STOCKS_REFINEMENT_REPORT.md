# Quality Stocks — Refinement Report (Phase 3, Task C)

**Generated**: 2026-05-11
**Status**: ✅ Refinement complete. Recommendation: **promote `v5_combined`** as the active variant.

---

## 1. Hypothesis

The Phase 2 walk-forward verdict on the baseline configuration was 🔴 OVERFIT (median OOS Sharpe **-0.208** across 5 folds). The honest interpretation in PHASE2_REPORT.md flagged three suspected causes:

| Suspected cause | Variant tested |
|---|---|
| Trend filter SMA(50/200) is too slow for the post-2020 whip-saw market — it stays "uptrend" through the early 2022 selloff and stays "downtrend" through the mid-2023 recovery. | **V2 — faster trend** (20/100) |
| Momentum lookback 126/skip 10 (≈6 months) is too long for the modern regime — it gives stale picks. | **V3 — shorter momentum** (60/5, ≈3 months) |
| The IEF bond fallback in 2022 backfired because IEF lost ~15% during the rate-hike cycle. | **V4 — no bond fallback** (cash within sleeve in bear regime) |
| All three together — does the combination compound the fix or compound noise? | **V5 — combined** (V2 + V3 + V4) |

These are **directionally-motivated, pre-registered hypotheses** — not the output of a grid search. The variants are exactly four; no auxiliary tweaks, no per-fold re-tuning.

**Implementation note**: while wiring up V2 I discovered the baseline strategy was reading `momentum_lookback`/`momentum_skip` from config but had the trend MAs **hardcoded** in `regime.is_market_uptrend(...)`. The baseline was therefore not configurable on this axis; V2 required a one-line strategy fix that now plumbs `trend_short_ma`/`trend_long_ma` through. Documented in [strategies/quality_stocks/strategy.py:_trend_kwargs](strategies/quality_stocks/strategy.py).

---

## 2. Results

5 folds × 5 variants, train 4y / test 1y, step 1y. Window 2016-01-04 → 2025-12-31. Capital €100k. Costs 5bps commission + 5bps slippage.

### 2.1 Summary

| Variant | Description | Median OOS Sharpe | p25 | p75 | Verdict |
|---|---|---:|---:|---:|---|
| baseline | 50/200 trend, 126/10 mom, IEF fallback | **-0.208** | -0.269 | -0.146 | 🔴 OVERFIT |
| v2 | 20/100 trend (faster) | **+0.911** | -0.172 | +1.401 | 🟡 MARGINAL |
| v3 | 60/5 momentum (shorter) | **+0.014** | -0.441 | +0.227 | 🔴 OVERFIT |
| v4 | no bond fallback (cash in bear) | **+0.636** | +0.225 | +1.430 | 🟢 ROBUST |
| **v5** | **v2 + v3 + v4 combined** | **+0.745** | **+0.480** | +0.779 | **🟢 ROBUST** |

### 2.2 Per-fold breakdown

| Variant | Fold 1 (2020) | Fold 2 (2021) | Fold 3 (2022) | Fold 4 (2023) | Fold 5 (2024) |
|---|---:|---:|---:|---:|---:|
| baseline | **+1.76** | -0.27 | **-1.50** | -0.21 | -0.15 |
| v2 | +1.80 | -0.17 | -0.79 | +1.40 | +0.91 |
| v3 | +1.61 | +0.01 | **-1.50** | -0.44 | +0.23 |
| v4 | +1.43 | +0.23 | **nan** (no trades) | +1.05 | +0.20 |
| **v5** | +1.16 | **+0.78** | **+0.06** | +0.48 | +0.74 |

**Reading the table**:
- Fold 3 (2022) is the destroyer for baseline / V3. The trend filter (50/200) stays "uptrend" until April-May 2022 and then immediately falls through; bond fallback IEF crashed too. V4 fixes this by sitting in cash, but the strategy effectively does nothing for most of 2022 (n_trades=0, Sharpe=NaN). V5 cleans this up because its 20/100 trend exits earlier *and* there's no bond drag.
- V2 alone has Sharpe **-0.79** in fold 3 — fixing the trend helps but the IEF crash still hurts.
- V5 is the *most consistent* variant (p75 − p25 = **+0.30**, vs V4's +1.21 spread). Every fold is positive or near-zero. **The narrow spread is what makes V5 preferable to V4** despite a marginally lower p75.

### 2.3 Decomposition of the fix

- **V4 alone** (just removing IEF) cleared ROBUST. So the dominant cause of the baseline's OVERFIT was the bond fallback.
- **V2 alone** improved fold 4 + 5 dramatically but couldn't save fold 3 — the trend filter still missed the regime change in time to protect 2022.
- **V3 alone** did almost nothing (median +0.014). Shortening the momentum window is not the dominant lever.
- **V5 (all three)** is the most consistent — V2's faster trend + V4's no-bond-fallback work together: the strategy exits to cash earlier (V2) and stays in cash instead of crashing IEF (V4). V3 contributes marginally; without it V5 would essentially equal V4 with V2's trend overlay.

---

## 3. Statistical caveats

5 folds is **small**. Some inferences are weaker than they look:

1. **Confirmation bias is real**: the variant designs were informed by what we saw on the same 2016-2025 panel. The fact that V4/V5 "work" is partly because we knew where they had to work (fold 3). The numerical Sharpe gain from baseline → V5 (Δ +0.953) is large enough that the *direction* is almost certainly correct, but the *magnitude* is plausibly inflated.

2. **No power calculation**: with 5 fold-Sharpes per variant, a t-test against zero has < 20 degrees of freedom — far from rigorous. The verdict thresholds (ROBUST ≥ 0.40 with p25 > 0) are conservative heuristics, not p-values.

3. **The verdict thresholds were set BEFORE we ran V2-V5** (they're inherited from Phase 1 and used identically for pair_trading_ITA's archived verdict). So we did not move the goalposts.

4. **No fold is truly independent** — they overlap in the training window. The walk-forward design mitigates this, but the price panel itself spans only one rate-cycle and one major drawdown (2022). A 2008-style event is unrepresented.

5. **The biggest unknown is what happens in market regimes we haven't seen**:
   - 2014-2019 (low-vol bull) — never tested. The strategy might be far less impressive when there's nothing to filter out.
   - A real 2008-style drawdown — V4/V5 sit in cash but never had to navigate -50% over 18 months.

**What would actually validate this**: forward paper trading for 6-12 months, OR backtesting on 2014-2019 (data we have but haven't used). The latter is the cheapest next step. **Recommended as the highest-priority Phase 4 test.**

---

## 4. Per-variant verdict

| Variant | Verdict | One-liner |
|---|---|---|
| **baseline** | 🔴 OVERFIT | IEF fallback in 2022 + slow trend = -0.21 OOS Sharpe |
| **v2** | 🟡 MARGINAL | High median (+0.91) but fold 3 still bad — IEF still hurts |
| **v3** | 🔴 OVERFIT | Momentum length is not the dominant lever; basically baseline |
| **v4** | 🟢 ROBUST | Removing IEF alone clears the threshold |
| **v5** | 🟢 ROBUST | **Most consistent — p25 = +0.48, no fold negative** |

---

## 5. Final recommendation

**Promote V5 (`quality_stocks_v5_combined.yaml`) to the active variant.**

Reasoning:
- V4 also clears ROBUST and is a *simpler* change (one parameter flip), which would normally be preferable on parsimony grounds.
- However V4 has Fold 3 = NaN (zero trades, Sharpe undefined). The realised return for that fold is 0% by definition, but a strategy that does nothing for an entire year is operationally awkward — the equity sleeve sits idle while the user pays opportunity cost.
- V5 actually trades through 2022 (31 trades) and earns +0.06 Sharpe — barely positive, but at least the model is engaging with the market.
- V5's p25 = +0.48 is the best of any variant. If we get unlucky on the next fold, V5 is the most likely to still have a positive Sharpe.

The trade-off is parsimony vs consistency. I'm choosing consistency.

### Caveat on the recommendation

Both V4 and V5 should be considered **provisional until forward-validated**. If you want a smaller risk profile, deploy V5 with a **reduced equity-sleeve allocation** (e.g. 20% instead of 30%) until at least 6 months of live paper trading confirms the OOS profile.

---

## 6. Honesty note

These four variants were chosen with prior knowledge of the baseline's specific failure modes (especially fold 3, the 2022 bear). That is **confirmation bias** in a non-trivial way: I didn't run a grid search, but I did know where the strategy was bleeding before choosing fixes.

What I did NOT do:
- Did NOT iterate on V5 to nudge any single metric. The configs were written before any results came back; no metrics were tuned in-loop.
- Did NOT cherry-pick the window. 2016-01 → 2025-12 was inherited from Phase 2.
- Did NOT change the verdict thresholds.
- Did NOT remove or hide fold 3 from the analysis (it's the most informative fold).

What I cannot promise:
- That V5 will work on data we haven't seen. The lesson from pair_trading_ITA iter-5 is exactly this: a model that looks robust on its training panel can still fail in production.
- That the +0.745 median is the *real* OOS Sharpe and not the upper end of a wide distribution.

**Treat V5's promotion as a tentative working assumption, not a validated edge.** Phase 4 priorities (next page):

1. **HIGH**: Backtest V5 on 2014-2019 — fully out-of-sample relative to the data that informed the variants.
2. **HIGH**: Paper-trade V5 in the equity sleeve at reduced allocation (e.g. 20% instead of 30%).
3. **MED**: Re-test V4 with a regime-aware short-term cash sleeve substitute (e.g. SHY or BIL) — the parsimony argument for V4 deserves a fair hearing.
4. **LOW**: Investigate fold 1 (2020) Sharpe drift between PHASE2_REPORT (+1.87) and the Phase 3 rerun (+1.76). 6% drift suggests cache state matters; worth pinning down.
