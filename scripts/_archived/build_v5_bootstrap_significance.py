"""Bootstrap CI on the OOS concatenated daily returns of a walkforward run.

Resamples daily returns 1000× with replacement, computes annualised Sharpe
on each resample, and reports the 95% CI plus a p-value vs Sharpe=0.

Writes ``outputs/validation/v5_statistical_significance.json`` and prints
to stdout.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

# --- bootstrap ---
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# ---

import numpy as np
import pandas as pd


def _sharpe(returns: np.ndarray, trading_days: int = 252) -> float:
    if returns.size < 2:
        return float("nan")
    sd = returns.std(ddof=1)
    if sd == 0 or not np.isfinite(sd):
        return float("nan")
    return float(returns.mean() / sd * math.sqrt(trading_days))


def bootstrap(returns: np.ndarray, n_iter: int = 1000, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    n = returns.size
    if n < 30:
        return {"insufficient_data": True, "n_obs": int(n)}
    samples = np.empty(n_iter, dtype=float)
    for i in range(n_iter):
        idx = rng.integers(0, n, size=n)
        samples[i] = _sharpe(returns[idx])
    point = _sharpe(returns)
    lower, upper = np.percentile(samples, [2.5, 97.5])
    # p-value: two-sided, fraction of resampled Sharpes that crossed zero from the same side as the point
    if point >= 0:
        p_value = float((samples <= 0).mean() * 2)  # two-sided
    else:
        p_value = float((samples >= 0).mean() * 2)
    p_value = min(p_value, 1.0)
    return {
        "n_obs": int(n),
        "point_sharpe": round(point, 4),
        "ci_lower_2_5pct": round(float(lower), 4),
        "ci_upper_97_5pct": round(float(upper), 4),
        "ci_excludes_zero": bool(lower > 0 or upper < 0),
        "p_value_two_sided": round(p_value, 5),
        "bootstrap_iterations": n_iter,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant-dir", required=True)
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--iter", type=int, default=1000)
    args = ap.parse_args(argv)

    variant_dir = Path(args.variant_dir)
    eq_path = variant_dir / "equity_oos_concatenated.csv"
    if not eq_path.exists():
        raise FileNotFoundError(eq_path)

    eq_df = pd.read_csv(eq_path, index_col=0, parse_dates=True)
    eq = eq_df.iloc[:, 0]
    rets = eq.pct_change().dropna().to_numpy()
    boot = bootstrap(rets, n_iter=args.iter)

    out_json = Path(args.out_json) if args.out_json else (
        _REPO_ROOT / "outputs" / "validation" / "v5_statistical_significance.json"
    )
    out_json.parent.mkdir(parents=True, exist_ok=True)
    boot["variant"] = variant_dir.name
    boot["window"] = {"start": str(eq.index[0].date()), "end": str(eq.index[-1].date())}
    boot["conclusion"] = (
        "Sharpe statistically significant (95% CI excludes 0)"
        if boot.get("ci_excludes_zero") else
        "Sharpe NOT statistically significant (95% CI crosses 0)"
    )
    out_json.write_text(json.dumps(boot, indent=2, default=str), encoding="utf-8")
    print(json.dumps(boot, indent=2, default=str))
    print(f"saved -> {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
