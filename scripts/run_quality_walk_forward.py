"""Walk-forward validation for QualityStocks.

3 folds, train 4y / test 1y, step 1y. Parameters are fixed (never tuned
per-fold). Output: distribution of OOS Sharpe / max DD per fold, with an
automatic verdict (ROBUST / MARGINAL / OVERFIT).

VERDICT thresholds (median OOS Sharpe across folds):
    >= 0.40  ROBUST
    >= 0.20  MARGINAL
    <  0.20  OVERFIT
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

# --- bootstrap ---
_REPO_ROOT = Path(__file__).resolve().parents[1]
_PARENT = _REPO_ROOT.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))
# ---

import pandas as pd

from quant_lab.core.analytics.metrics import compute_metrics
from quant_lab.core.backtest.engine import PortfolioBacktester
from quant_lab.core.data.providers.fmp_provider import FMPProvider
from quant_lab.core.data.storage import DataStorage, load_global_config
from quant_lab.strategies.quality_stocks import QualityStocks
from quant_lab.strategies.quality_stocks.runner import build_panel

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
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cfg = load_global_config()
    storage = DataStorage.from_config(cfg)
    fmp = FMPProvider()

    universe = fmp.get_index_constituents("sp500")
    log.info("universe: %d", len(universe))

    # One panel for the whole window (cached after first load)
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

    fold_results = []
    for k, (tr_s, tr_e, te_s, te_e) in enumerate(windows):
        log.info("fold %d/%d  train %s..%s  test %s..%s",
                 k + 1, len(windows), tr_s, tr_e, te_s, te_e)
        test_panel = panel.loc[pd.Timestamp(te_s):pd.Timestamp(te_e)]
        if test_panel.empty:
            log.warning("fold %d empty test panel", k)
            continue
        strat = QualityStocks(fmp=fmp, prefetch=False)  # prefetch happens on demand
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
        log.info("  -> sharpe=%.2f trades=%d return=%.2f%%",
                 metrics.get("sharpe") or 0,
                 len(res.trades), metrics.get("total_return_pct") or 0)

    # Aggregate verdict
    sharpes = [r["sharpe"] for r in fold_results if r["sharpe"] is not None
               and pd.notna(r["sharpe"])]
    if not sharpes:
        median, p25, p75 = float("nan"), float("nan"), float("nan")
        verdict = "INSUFFICIENT_DATA"
    else:
        sharpes.sort()
        median = statistics.median(sharpes)
        # Simple quartile approximation
        n = len(sharpes)
        p25 = sharpes[max(0, n // 4)] if n > 1 else sharpes[0]
        p75 = sharpes[min(n - 1, (3 * n) // 4)] if n > 1 else sharpes[0]
        verdict = _classify(median, p25)

    out = dict(
        strategy_id="quality_stocks",
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

    out_path = Path(args.out) if args.out else (
        _REPO_ROOT / "outputs" / "quality_stocks" / "walk_forward_verdict.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")

    badge = {"ROBUST": "ROBUST", "MARGINAL": "MARGINAL",
             "OVERFIT": "OVERFIT"}.get(verdict, verdict)
    print(json.dumps(out, indent=2, default=str))
    print(f"\nVERDICT: {badge}  (median Sharpe OOS = {median:.3f})")
    print(f"saved -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
