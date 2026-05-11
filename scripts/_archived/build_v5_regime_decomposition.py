"""Group walk-forward OOS folds by macro regime + emit a per-regime report.

Regimes (adapted to the actual data window 2009-2026):

  Post-crisis recovery       : 2009-01 → 2012-12  (QE era, vol → lower, deflation→reflation)
  Long bull                  : 2013-01 → 2019-12  (low vol, zero rates, structural bull)
  COVID + inflation          : 2020-01 → 2022-12  (crash+rebound, regime shift, inflation spike)
  Normalization              : 2023-01 → 2026-12  (higher rates, sector dispersion)

Per regime we compute on the OOS fold set whose test_start falls inside:
  - mean Sharpe, median Sharpe
  - n folds inside
  - win rate (fold Sharpe > 0)
  - cumulative return (chained OOS equity within the regime)
  - SPY benchmark cumulative return same period

Output:
  outputs/validation/regime_performance.html
  outputs/validation/regime_performance.json
"""
from __future__ import annotations

import argparse
import json
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
import plotly.graph_objects as go

from core.data.storage import DataStorage, load_global_config


REGIMES = [
    ("post_crisis", "Post-crisis recovery", date(2009, 1, 1), date(2012, 12, 31)),
    ("long_bull",   "Long bull",            date(2013, 1, 1), date(2019, 12, 31)),
    ("covid_infl",  "COVID + inflation",    date(2020, 1, 1), date(2022, 12, 31)),
    ("normalize",   "Rate normalization",   date(2023, 1, 1), date(2026, 12, 31)),
]


def _classify(median_sharpe: float, win_rate: float) -> str:
    if median_sharpe > 0.5 and win_rate >= 0.66:
        return "STRONG"
    if median_sharpe < 0 or win_rate < 0.4:
        return "WEAK"
    return "NEUTRAL"


def build(variant_dir: Path, out_html: Path, out_json: Path) -> dict:
    verdict_path = variant_dir / "walk_forward_verdict_extended.json"
    if not verdict_path.exists():
        verdict_path = variant_dir / "walk_forward_verdict.json"
    raw = json.loads(verdict_path.read_text(encoding="utf-8"))
    folds = [f for f in raw["folds"]
             if f.get("sharpe") is not None and not pd.isna(f.get("sharpe"))
             and (f.get("n_trades") or 0) > 0]

    eq_path = variant_dir / "equity_oos_concatenated.csv"
    eq = None
    if eq_path.exists():
        eq_df = pd.read_csv(eq_path, index_col=0, parse_dates=True)
        eq = eq_df.iloc[:, 0]

    # SPY benchmark (full window) for comparison
    storage = DataStorage.from_config(load_global_config())
    spy = storage.get_prices("SPY", None, None)
    if not spy.empty:
        spy_series = spy["adj_close"].copy()
        spy_series.index = pd.to_datetime(spy.index)
    else:
        spy_series = pd.Series(dtype=float)

    results = []
    for rid, label, r_start, r_end in REGIMES:
        in_regime = []
        for f in folds:
            tstart = date.fromisoformat(f["test_start"])
            if r_start <= tstart <= r_end:
                in_regime.append(f)
        sharpes = [f["sharpe"] for f in in_regime]
        returns = [f["total_return_pct"] for f in in_regime]
        win_rate = sum(1 for s in sharpes if s > 0) / len(sharpes) if sharpes else 0.0
        v5_cum = float("nan")
        spy_cum = float("nan")
        if eq is not None and not eq.empty:
            mask = (eq.index >= pd.Timestamp(r_start)) & (eq.index <= pd.Timestamp(r_end))
            slc = eq[mask]
            if len(slc) > 1:
                v5_cum = float((slc.iloc[-1] / slc.iloc[0] - 1) * 100)
        if spy_series is not None and not spy_series.empty:
            mask = (spy_series.index >= pd.Timestamp(r_start)) & (spy_series.index <= pd.Timestamp(r_end))
            slc = spy_series[mask]
            if len(slc) > 1:
                spy_cum = float((slc.iloc[-1] / slc.iloc[0] - 1) * 100)
        median_sharpe = float(statistics.median(sharpes)) if sharpes else float("nan")
        mean_sharpe = float(np.mean(sharpes)) if sharpes else float("nan")
        verdict = _classify(median_sharpe, win_rate) if sharpes else "INSUFFICIENT_DATA"
        results.append({
            "regime_id": rid, "label": label,
            "start": r_start.isoformat(), "end": r_end.isoformat(),
            "n_folds": len(in_regime),
            "mean_sharpe": round(mean_sharpe, 3),
            "median_sharpe": round(median_sharpe, 3),
            "win_rate_positive": round(win_rate, 3),
            "v5_cumulative_return_pct": round(v5_cum, 2) if not np.isnan(v5_cum) else None,
            "spy_cumulative_return_pct": round(spy_cum, 2) if not np.isnan(spy_cum) else None,
            "v5_minus_spy_pct": (round(v5_cum - spy_cum, 2)
                                  if not np.isnan(v5_cum) and not np.isnan(spy_cum) else None),
            "verdict": verdict,
        })

    out = {
        "variant": raw.get("variant"),
        "window": raw.get("window"),
        "regimes": results,
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")

    # ---- HTML ----
    df = pd.DataFrame(results)

    # Equity chart with shaded regime backgrounds
    fig = go.Figure()
    if eq is not None and not eq.empty:
        fig.add_trace(go.Scatter(x=eq.index, y=eq.values, mode="lines",
                                  name="V5 OOS equity", line=dict(width=2, color="#2563eb")))
    if spy_series is not None and not spy_series.empty and eq is not None and not eq.empty:
        # Normalise SPY to start at the same equity value within the V5 window
        spy_in = spy_series.loc[eq.index[0]:eq.index[-1]]
        if not spy_in.empty:
            spy_norm = spy_in / spy_in.iloc[0] * float(eq.iloc[0])
            fig.add_trace(go.Scatter(x=spy_norm.index, y=spy_norm.values, mode="lines",
                                      name="SPY (normalised)",
                                      line=dict(width=1, dash="dash", color="#6b7280")))

    rgcols = ["#dbeafe", "#fef9c3", "#fed7aa", "#e9d5ff"]
    for (rid, label, r_start, r_end), colour in zip(REGIMES, rgcols):
        fig.add_vrect(x0=pd.Timestamp(r_start), x1=pd.Timestamp(r_end),
                       fillcolor=colour, opacity=0.35, line_width=0,
                       annotation_text=label, annotation_position="top left",
                       annotation=dict(font_size=10, font_color="#374151"))
    fig.update_layout(template="plotly_white", height=420,
                       title="V5 OOS equity vs SPY — regime overlay",
                       yaxis_title="EUR")
    eq_html = fig.to_html(include_plotlyjs="cdn", full_html=False)

    table = df.to_html(index=False, escape=False)
    crit = []
    for r in results:
        v = r["verdict"]
        colour = {"STRONG": "#16a34a", "WEAK": "#dc2626",
                   "NEUTRAL": "#f59e0b", "INSUFFICIENT_DATA": "#6b7280"}.get(v, "#6b7280")
        crit.append(
            f"<li><b>{r['label']}</b> "
            f"<span style='display:inline-block;padding:1px 8px;border-radius:8px;"
            f"background:{colour};color:white;font-size:0.85em;'>{v}</span> "
            f"— {r['n_folds']} folds, median Sharpe "
            f"<b>{r['median_sharpe']:+.3f}</b>, "
            f"win rate {r['win_rate_positive']*100:.0f}%, "
            f"V5 cumulative {r['v5_cumulative_return_pct']}% "
            f"vs SPY {r['spy_cumulative_return_pct']}% "
            f"(diff {r['v5_minus_spy_pct']:+}%)</li>"
        )

    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>V5 — regime decomposition</title>
<style>body{{font-family:-apple-system,sans-serif;max-width:1200px;margin:24px auto;padding:0 16px;}}
table{{width:100%;border-collapse:collapse;font-size:0.9em;}}
th,td{{border:1px solid #e5e7eb;padding:6px 10px;text-align:left;}}
th{{background:#f9fafb;}}
h1,h2{{border-bottom:1px solid #e5e7eb;padding-bottom:6px;}}</style>
</head><body>
<h1>Quality Stocks V5 — Regime Decomposition</h1>
<h2>Equity vs SPY (regime overlay)</h2>
{eq_html}
<h2>Per-regime metrics</h2>
{table}
<h2>Interpretation</h2>
<ul>{''.join(crit)}</ul>
</body></html>"""
    out_html.write_text(page, encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant-dir", required=True)
    ap.add_argument("--out-html", default=None)
    ap.add_argument("--out-json", default=None)
    args = ap.parse_args(argv)

    variant_dir = Path(args.variant_dir)
    out_html = Path(args.out_html) if args.out_html else (
        _REPO_ROOT / "outputs" / "validation" / "regime_performance.html"
    )
    out_json = Path(args.out_json) if args.out_json else (
        _REPO_ROOT / "outputs" / "validation" / "regime_performance.json"
    )
    build(variant_dir, out_html, out_json)
    print(f"HTML: {out_html}")
    print(f"JSON: {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
