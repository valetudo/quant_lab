"""Post-process a walkforward_<variant>/ run into the V2 extended report.

Reads the existing ``walk_forward_verdict.json`` + the per-fold ``equity.csv``
files written by ``run_quality_walk_forward.py`` and emits:

  - ``per_fold_metrics.csv``                       (one row per fold, ready for spreadsheet)
  - ``walk_forward_dashboard.html``                (4-panel Plotly dashboard)
  - ``walk_forward_verdict_extended.json``         (richer summary + V2.3 verdict)

Doesn't re-run any backtest. Idempotent.

V2.3 verdict thresholds (stricter than the inherited Phase-2 thresholds):
  - ROBUST: median Sharpe > 0.5 AND p25 > 0.2 AND ≥70% folds positive
  - MARGINAL: median Sharpe > 0.2 AND ≥50% folds positive
  - OVERFIT: otherwise
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import date
from pathlib import Path

# --- bootstrap ---
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# ---

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    return float(np.percentile(np.asarray(values, dtype=float), q))


def _classify_v23(median: float, p25: float, hit_rate_pos: float) -> str:
    if median > 0.5 and p25 > 0.2 and hit_rate_pos >= 0.70:
        return "ROBUST"
    if median > 0.2 and hit_rate_pos >= 0.50:
        return "MARGINAL"
    return "OVERFIT"


def _t_test_against_zero(values: list[float]) -> tuple[float, float]:
    """Two-sided one-sample t-test for H0: mean(values) == 0. Returns (t, p)."""
    arr = np.asarray([v for v in values if v is not None and not math.isnan(v)], dtype=float)
    n = len(arr)
    if n < 2:
        return float("nan"), float("nan")
    mean = float(arr.mean())
    sd = float(arr.std(ddof=1))
    if sd == 0:
        return float("inf"), 0.0
    t = mean / (sd / math.sqrt(n))
    try:
        from scipy.stats import t as t_dist
        p = float(2 * (1 - t_dist.cdf(abs(t), df=n - 1)))
    except ImportError:
        # Crude approximation if scipy isn't available — should be there per requirements
        z = abs(t)
        p = max(0.0, min(1.0, 2 * (1 - 0.5 * (1 + math.erf(z / math.sqrt(2))))))
    return float(t), float(p)


def _worst_12m_drawdown(equity: pd.Series) -> dict:
    """Find the worst peak-to-trough drawdown within any rolling 252-day window."""
    if equity is None or equity.empty or len(equity) < 60:
        return {"worst_pct": 0.0, "peak_date": None, "trough_date": None}
    rolling_max = equity.rolling(window=min(252, len(equity)), min_periods=1).max()
    dd = (equity / rolling_max - 1.0)
    if dd.empty:
        return {"worst_pct": 0.0, "peak_date": None, "trough_date": None}
    trough_idx = dd.idxmin()
    if trough_idx is pd.NaT:
        return {"worst_pct": 0.0, "peak_date": None, "trough_date": None}
    # Find peak in the same rolling window
    start_lookback = max(0, equity.index.get_loc(trough_idx) - 252)
    peak_idx = equity.iloc[start_lookback:equity.index.get_loc(trough_idx) + 1].idxmax()
    return {
        "worst_pct": round(float(dd.loc[trough_idx]) * 100, 2),
        "peak_date": peak_idx.date().isoformat() if hasattr(peak_idx, "date") else str(peak_idx),
        "trough_date": trough_idx.date().isoformat() if hasattr(trough_idx, "date") else str(trough_idx),
    }


def build_extended(variant_dir: Path, verbose: bool = True) -> dict:
    verdict_path = variant_dir / "walk_forward_verdict.json"
    if not verdict_path.exists():
        raise FileNotFoundError(verdict_path)
    raw = json.loads(verdict_path.read_text(encoding="utf-8"))
    folds = raw["folds"]

    sharpes = [f["sharpe"] for f in folds
               if f.get("sharpe") is not None and not math.isnan(f["sharpe"])]
    returns = [f["total_return_pct"] for f in folds
               if f.get("total_return_pct") is not None]
    n_trades = [int(f.get("n_trades") or 0) for f in folds]

    pos_count = sum(1 for s in sharpes if s > 0)
    pos05_count = sum(1 for s in sharpes if s > 0.5)
    pos10_count = sum(1 for s in sharpes if s > 1.0)
    hit_rate_pos = pos_count / len(sharpes) if sharpes else 0.0
    hit_rate_05 = pos05_count / len(sharpes) if sharpes else 0.0
    hit_rate_10 = pos10_count / len(sharpes) if sharpes else 0.0

    median = float(statistics.median(sharpes)) if sharpes else float("nan")
    mean = float(np.mean(sharpes)) if sharpes else float("nan")
    std = float(np.std(sharpes, ddof=1)) if len(sharpes) > 1 else 0.0
    p10, p25, p50, p75, p90 = (_percentile(sharpes, q) for q in (10, 25, 50, 75, 90))

    worst_fold = min(folds, key=lambda f: f.get("sharpe") or 99) if folds else None
    best_fold = max(folds, key=lambda f: f.get("sharpe") or -99) if folds else None

    # Concatenated OOS equity → rolling 12-month drawdown
    eq_concat_path = variant_dir / "equity_oos_concatenated.csv"
    worst_12m: dict = {"worst_pct": 0.0, "peak_date": None, "trough_date": None}
    if eq_concat_path.exists():
        eq_df = pd.read_csv(eq_concat_path, index_col=0, parse_dates=True)
        eq_series = eq_df.iloc[:, 0]
        worst_12m = _worst_12m_drawdown(eq_series)

    t_stat, p_value = _t_test_against_zero(sharpes)
    verdict_v23 = _classify_v23(median, p25, hit_rate_pos)

    summary = {
        "n_folds": len(folds),
        "n_sharpe_observations": len(sharpes),
        "mean_oos_sharpe": round(mean, 3),
        "median_oos_sharpe": round(median, 3),
        "std_oos_sharpe": round(std, 3),
        "p10_oos_sharpe": round(p10, 3),
        "p25_oos_sharpe": round(p25, 3),
        "p50_oos_sharpe": round(p50, 3),
        "p75_oos_sharpe": round(p75, 3),
        "p90_oos_sharpe": round(p90, 3),
        "hit_rate_positive": round(hit_rate_pos, 3),
        "hit_rate_above_0_5": round(hit_rate_05, 3),
        "hit_rate_above_1_0": round(hit_rate_10, 3),
        "t_stat_vs_zero": round(t_stat, 3),
        "p_value_vs_zero": round(p_value, 5),
        "verdict_v23": verdict_v23,
        "verdict_inherited": raw["summary"].get("verdict"),
        "worst_fold": {
            "fold": worst_fold["fold"],
            "test_start": worst_fold["test_start"],
            "test_end": worst_fold["test_end"],
            "sharpe": worst_fold.get("sharpe"),
            "n_trades": worst_fold.get("n_trades"),
        } if worst_fold else None,
        "best_fold": {
            "fold": best_fold["fold"],
            "test_start": best_fold["test_start"],
            "test_end": best_fold["test_end"],
            "sharpe": best_fold.get("sharpe"),
            "n_trades": best_fold.get("n_trades"),
        } if best_fold else None,
        "worst_rolling_12m_drawdown": worst_12m,
    }

    # Write per-fold CSV
    per_fold_df = pd.DataFrame(folds)
    per_fold_df.to_csv(variant_dir / "per_fold_metrics.csv", index=False)

    extended = {
        "strategy_id": raw["strategy_id"],
        "variant": raw.get("variant"),
        "window": raw.get("window"),
        "params": raw.get("params"),
        "folds": folds,
        "summary": summary,
    }
    (variant_dir / "walk_forward_verdict_extended.json").write_text(
        json.dumps(extended, indent=2, default=str), encoding="utf-8")

    if verbose:
        print(f"variant={raw.get('variant')}  folds={summary['n_folds']}  "
              f"median={summary['median_oos_sharpe']:+.3f}  "
              f"p25={summary['p25_oos_sharpe']:+.3f}  "
              f"hit_rate>0={summary['hit_rate_positive']*100:.0f}%  "
              f"verdict_v23={summary['verdict_v23']}")
    return extended


def build_dashboard(variant_dir: Path) -> Path:
    """Plotly HTML dashboard — 4 panels: equity, fold sharpe bar, histogram, n_trades."""
    extended_path = variant_dir / "walk_forward_verdict_extended.json"
    if not extended_path.exists():
        raise FileNotFoundError("run build_extended() first")
    data = json.loads(extended_path.read_text(encoding="utf-8"))
    folds = data["folds"]
    s = data["summary"]

    folds_df = pd.DataFrame(folds)

    # 1) OOS concatenated equity
    eq_path = variant_dir / "equity_oos_concatenated.csv"
    eq_html = "<p>No equity_oos_concatenated.csv on disk.</p>"
    if eq_path.exists():
        eq_df = pd.read_csv(eq_path, index_col=0, parse_dates=True)
        eq = eq_df.iloc[:, 0]
        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(x=eq.index, y=eq.values, mode="lines",
                                     name="OOS equity",
                                     line=dict(width=2, color="#2563eb")))
        fig_eq.update_layout(template="plotly_white", height=380,
                              title=f"OOS equity (concatenated across "
                                    f"{s['n_folds']} folds)",
                              xaxis_title="date", yaxis_title="EUR")
        eq_html = fig_eq.to_html(include_plotlyjs="cdn", full_html=False, div_id="eq")

    # 2) Per-fold Sharpe bar (coloured)
    fold_labels = [f"f{int(r['fold'])}: {r['test_start'][:7]}" for _, r in folds_df.iterrows()]
    sharpe_vals = folds_df["sharpe"].fillna(0).tolist()
    colours = ["#16a34a" if s > 0.4 else "#f59e0b" if s > 0 else "#dc2626" for s in sharpe_vals]
    fig_bar = go.Figure([go.Bar(x=fold_labels, y=sharpe_vals, marker_color=colours)])
    fig_bar.add_hline(y=0, line_dash="dot", line_color="gray")
    fig_bar.add_hline(y=0.5, line_dash="dot", line_color="#16a34a",
                      annotation_text="0.5 (good)")
    fig_bar.update_layout(template="plotly_white", height=320,
                          title="OOS Sharpe per fold",
                          yaxis_title="Sharpe", xaxis_title="Fold (test start)",
                          margin=dict(l=0, r=0, t=40, b=80))
    bar_html = fig_bar.to_html(include_plotlyjs=False, full_html=False, div_id="bar")

    # 3) Sharpe histogram + box
    fig_hist = go.Figure()
    fig_hist.add_trace(go.Histogram(x=sharpe_vals, nbinsx=10, name="distribution",
                                     marker_color="#4c78a8"))
    fig_hist.add_vline(x=s["median_oos_sharpe"], line_dash="dot",
                       annotation_text=f"median {s['median_oos_sharpe']:+.2f}")
    fig_hist.update_layout(template="plotly_white", height=300,
                            title="OOS Sharpe distribution",
                            xaxis_title="Sharpe", yaxis_title="N folds",
                            margin=dict(l=0, r=0, t=40, b=20))
    hist_html = fig_hist.to_html(include_plotlyjs=False, full_html=False, div_id="hist")

    # 4) Trade count per fold
    n_trade_vals = folds_df["n_trades"].fillna(0).astype(int).tolist()
    fig_tr = go.Figure([go.Bar(x=fold_labels, y=n_trade_vals, marker_color="#888")])
    fig_tr.update_layout(template="plotly_white", height=300,
                         title="Trade count per fold",
                         yaxis_title="N trades", xaxis_title="",
                         margin=dict(l=0, r=0, t=40, b=80))
    tr_html = fig_tr.to_html(include_plotlyjs=False, full_html=False, div_id="tr")

    # Verdict banner
    verdict_colour = {"ROBUST": "#16a34a", "MARGINAL": "#f59e0b",
                      "OVERFIT": "#dc2626"}.get(s["verdict_v23"], "#6b7280")
    banner = (
        f"<div style='padding:14px 18px;border-radius:8px;"
        f"background:{verdict_colour};color:white;margin:18px 0;font-size:1.05em;'>"
        f"<b>V2.3 Verdict: {s['verdict_v23']}</b>"
        f" &nbsp;•&nbsp; median OOS Sharpe <b>{s['median_oos_sharpe']:+.3f}</b>"
        f" &nbsp;•&nbsp; p25 {s['p25_oos_sharpe']:+.3f}"
        f" &nbsp;•&nbsp; p75 {s['p75_oos_sharpe']:+.3f}"
        f" &nbsp;•&nbsp; hit-rate&nbsp;>&nbsp;0: {s['hit_rate_positive']*100:.0f}%"
        f" &nbsp;•&nbsp; t-test p-value vs 0: <b>{s['p_value_vs_zero']:.5f}</b>"
        f"</div>"
    )

    worst_12m = s["worst_rolling_12m_drawdown"]
    worst_block = ""
    if worst_12m and worst_12m.get("peak_date"):
        worst_block = (
            f"<p>Worst rolling 12-month drawdown: "
            f"<b>{worst_12m['worst_pct']:.2f}%</b>"
            f" (peak {worst_12m['peak_date']} → trough {worst_12m['trough_date']}).</p>"
        )

    folds_table_html = folds_df.to_html(index=False, classes="folds")

    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>V5 walk-forward dashboard — {data.get('variant')}</title>
<style>
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         max-width:1300px;margin:24px auto;padding:0 16px;color:#1f2937; }}
  h1,h2 {{ border-bottom:1px solid #e5e7eb;padding-bottom:6px; }}
  .grid {{ display:grid;grid-template-columns:repeat(2,1fr);gap:18px; }}
  table.folds {{ width:100%;border-collapse:collapse;font-size:0.85em; }}
  table.folds th, table.folds td {{ border:1px solid #e5e7eb;padding:4px 8px; }}
  table.folds th {{ background:#f9fafb; }}
</style></head><body>
<h1>Quality Stocks V5 — full-history walk-forward</h1>
<p>Variant <code>{data.get('variant')}</code> • window
   <code>{data['window']['start']} → {data['window']['end']}</code></p>
{banner}
<h2>Equity OOS</h2>
{eq_html}
{worst_block}
<h2>Per-fold breakdown</h2>
<div class="grid">{bar_html}{tr_html}</div>
<h2>Sharpe distribution</h2>
{hist_html}
<h2>Per-fold table</h2>
{folds_table_html}
</body></html>"""

    out_path = variant_dir / "walk_forward_dashboard.html"
    out_path.write_text(page, encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant-dir", required=True,
                    help="path to outputs/quality_stocks/walkforward_<variant>/")
    args = ap.parse_args(argv)

    p = Path(args.variant_dir)
    build_extended(p)
    dashboard = build_dashboard(p)
    print(f"dashboard: {dashboard}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
