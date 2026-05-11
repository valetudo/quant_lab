"""Walk-forward validation for QualityStocks.

5 folds (default), train 4y / test 1y, step 1y. Parameters are FIXED across
folds — no per-fold tuning. Output: distribution of OOS Sharpe / max DD per
fold, with an automatic verdict (ROBUST / MARGINAL / OVERFIT).

Verdict thresholds (median OOS Sharpe across folds):
    >= 0.40  ROBUST
    >= 0.20  MARGINAL
    <  0.20  OVERFIT

Phase 3 additions:
  - ``--config``   : pick a non-default strategy YAML (e.g. variant configs)
  - ``--variant``  : label used in the output directory
                     (outputs/quality_stocks/walkforward_<variant>/)
  - Per-fold OOS equity curve is now saved alongside the verdict, so the
    comparison dashboard can concatenate OOS series across folds.
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from datetime import date, datetime
from pathlib import Path

# --- bootstrap: add repo root to sys.path (no pip install needed) ---
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# ---

import pandas as pd

from core.analytics.metrics import compute_metrics
from core.backtest.engine import PortfolioBacktester
from core.data.providers.fmp_provider import FMPProvider
from core.data.storage import DataStorage, load_global_config
from strategies.quality_stocks import QualityStocks
from strategies.quality_stocks.runner import build_panel

log = logging.getLogger("walk_forward_quality")


def _rolling_windows(start: date, end: date, train_years: int, test_years: int,
                     step_years: int) -> list[tuple[date, date, date, date]]:
    out = []
    cur = start
    while True:
        tr_end = date(cur.year + train_years, cur.month, cur.day)
        te_end = date(tr_end.year + test_years, tr_end.month, tr_end.day)
        if te_end > end:
            break
        out.append((cur, tr_end, tr_end, te_end))
        cur = date(cur.year + step_years, cur.month, cur.day)
    return out


def _classify(median_sharpe: float, p25_sharpe: float) -> str:
    if median_sharpe >= 0.40 and p25_sharpe > 0:
        return "ROBUST"
    if median_sharpe >= 0.20:
        return "MARGINAL"
    return "OVERFIT"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default="2016-01-04", type=date.fromisoformat)
    ap.add_argument("--end", default="2025-12-31", type=date.fromisoformat)
    ap.add_argument("--train-years", type=int, default=4)
    ap.add_argument("--test-years", type=int, default=1)
    ap.add_argument("--step-years", type=int, default=1)
    ap.add_argument("--capital", type=float, default=100_000.0)
    ap.add_argument("--commission-bps", type=float, default=5.0)
    ap.add_argument("--slippage-bps", type=float, default=5.0)
    ap.add_argument("--config", default=None,
                    help="path to a strategy YAML; defaults to "
                         "strategies/quality_stocks/config.yaml")
    ap.add_argument("--variant", default="baseline",
                    help="label used in the output directory + verdict JSON")
    ap.add_argument("--out", default=None,
                    help="override output directory (default: "
                         "outputs/quality_stocks/walkforward_<variant>/)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cfg = load_global_config()
    storage = DataStorage.from_config(cfg)
    fmp = FMPProvider()
    config_path = Path(args.config) if args.config else None

    universe = fmp.get_index_constituents("sp500")
    log.info("variant=%s   universe: %d", args.variant, len(universe))

    panel = build_panel(storage, start=args.start, end=args.end,
                        universe_symbols=universe, extra=("SPY", "IEF"))
    if panel.empty:
        log.error("panel empty — run scripts/migrate_prices_to_fmp.py first")
        return 2
    log.info("panel: %d bars x %d cols", *panel.shape)

    windows = _rolling_windows(args.start, args.end,
                               args.train_years, args.test_years, args.step_years)
    log.info("walk-forward folds: %d", len(windows))
    if not windows:
        log.error("no folds — window too short")
        return 2

    out_root = Path(args.out) if args.out else (
        _REPO_ROOT / "outputs" / "quality_stocks" / f"walkforward_{args.variant}"
    )
    out_root.mkdir(parents=True, exist_ok=True)
    log.info("output dir: %s", out_root)

    fold_results: list[dict] = []
    oos_equities: list[pd.Series] = []   # for concatenation
    for k, (tr_s, tr_e, te_s, te_e) in enumerate(windows):
        log.info("fold %d/%d  train %s..%s  test %s..%s",
                 k + 1, len(windows), tr_s, tr_e, te_s, te_e)
        test_panel = panel.loc[pd.Timestamp(te_s):pd.Timestamp(te_e)]
        if test_panel.empty:
            log.warning("fold %d empty test panel", k)
            continue
        strat = QualityStocks(fmp=fmp, prefetch=False, config_path=config_path)
        bt = PortfolioBacktester(strat, test_panel,
                                 initial_capital_eur=args.capital,
                                 commission_bps=args.commission_bps,
                                 slippage_bps=args.slippage_bps)
        t0 = time.monotonic()
        res = bt.run()
        elapsed = time.monotonic() - t0
        eq = res.equity["equity"] if not res.equity.empty else pd.Series(dtype=float)
        metrics = compute_metrics(eq, res.trades, args.capital,
                                  open_count=res.open_count,
                                  exposure=res.exposure)
        fold_results.append(dict(
            fold=k + 1,
            train_start=str(tr_s), train_end=str(tr_e),
            test_start=str(te_s), test_end=str(te_e),
            n_trades=len(res.trades),
            elapsed_s=round(elapsed, 1),
            sharpe=metrics.get("sharpe"),
            sortino=metrics.get("sortino"),
            max_drawdown=metrics.get("max_drawdown"),
            total_return_pct=metrics.get("total_return_pct"),
            final_equity=metrics.get("final_equity"),
        ))
        # Save per-fold equity CSV
        fold_dir = out_root / f"fold_{k+1:02d}_{te_s}_{te_e}"
        fold_dir.mkdir(parents=True, exist_ok=True)
        if not eq.empty:
            eq.to_csv(fold_dir / "equity.csv", header=["equity_eur"])
            # For concatenation: normalize each fold to start at 1.0 then chain
            norm = eq / eq.iloc[0]
            norm.name = "eq_norm"
            oos_equities.append(norm)
        fold_dir.joinpath("metrics.json").write_text(
            json.dumps(metrics, indent=2, default=str), encoding="utf-8")
        log.info("  -> sharpe=%.2f trades=%d return=%.2f%%",
                 metrics.get("sharpe") or 0,
                 len(res.trades), metrics.get("total_return_pct") or 0)

    # Concatenated OOS equity: chain folds in date order.
    if oos_equities:
        chained: list[float] = []
        chained_idx: list[pd.Timestamp] = []
        running = args.capital
        for s in oos_equities:
            # series is normalised so s.iloc[0] == 1.0
            for ts, v in s.items():
                chained.append(float(v) * running)
                chained_idx.append(ts)
            running = chained[-1]
        oos_concat = pd.Series(chained, index=chained_idx, name="equity_oos_eur")
        oos_concat.to_csv(out_root / "equity_oos_concatenated.csv",
                          header=["equity_oos_eur"])

    # Aggregate verdict
    sharpes = [r["sharpe"] for r in fold_results if r["sharpe"] is not None
               and pd.notna(r["sharpe"])]
    if not sharpes:
        median, p25, p75 = float("nan"), float("nan"), float("nan")
        verdict = "INSUFFICIENT_DATA"
    else:
        sharpes.sort()
        median = statistics.median(sharpes)
        n = len(sharpes)
        p25 = sharpes[max(0, n // 4)] if n > 1 else sharpes[0]
        p75 = sharpes[min(n - 1, (3 * n) // 4)] if n > 1 else sharpes[0]
        verdict = _classify(median, p25)

    out = dict(
        strategy_id="quality_stocks",
        variant=args.variant,
        config_path=str(config_path) if config_path else "(default)",
        generated_at=datetime.utcnow().isoformat(),
        window={"start": str(args.start), "end": str(args.end)},
        params={
            "train_years": args.train_years,
            "test_years": args.test_years,
            "step_years": args.step_years,
            "capital": args.capital,
            "commission_bps": args.commission_bps,
            "slippage_bps": args.slippage_bps,
        },
        folds=fold_results,
        summary={
            "n_folds": len(fold_results),
            "median_sharpe_oos": median,
            "p25_sharpe_oos": p25,
            "p75_sharpe_oos": p75,
            "verdict": verdict,
        },
    )

    verdict_path = out_root / "walk_forward_verdict.json"
    verdict_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    # Back-compat: baseline variant ALSO writes to the legacy location
    # so the Quality Stocks page banner keeps working.
    if args.variant == "baseline":
        legacy = _REPO_ROOT / "outputs" / "quality_stocks" / "walk_forward_verdict.json"
        legacy.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")

    badge = verdict
    print(json.dumps(out, indent=2, default=str))
    print(f"\nVARIANT: {args.variant}  VERDICT: {badge}  (median Sharpe OOS = {median:.3f})")
    print(f"saved -> {verdict_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
