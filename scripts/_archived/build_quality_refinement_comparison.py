"""Build a single-file HTML comparison of Quality Stocks refinement variants.

Reads ``outputs/quality_stocks/walkforward_<variant>/walk_forward_verdict.json``
+ ``equity_oos_concatenated.csv`` for each variant and produces
``outputs/quality_stocks/refinement_comparison.html``.

Generated for Phase 3. Variants expected by default: baseline, v2, v3, v4, v5.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# --- bootstrap: add repo root to sys.path (no pip install needed) ---
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# ---

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

DEFAULT_VARIANTS = ["baseline", "v2", "v3", "v4", "v5"]

VARIANT_LABELS = {
    "baseline": "baseline (50/200 trend, 126/10 mom, IEF fallback)",
    "v2":       "V2 — faster trend (20/100)",
    "v3":       "V3 — shorter momentum (60/5)",
    "v4":       "V4 — no bond fallback (cash in bear)",
    "v5":       "V5 — V2+V3+V4 combined",
}

# Slightly distinguishable, colour-blind-friendly palette
PALETTE = {
    "baseline": "#888888",
    "v2":       "#4c78a8",
    "v3":       "#f58518",
    "v4":       "#54a24b",
    "v5":       "#e45756",
}


def _classify_now(median: float, p25: float) -> str:
    # Mirror the rule from run_quality_walk_forward.py
    if median is None or pd.isna(median):
        return "INSUFFICIENT_DATA"
    if median >= 0.40 and p25 > 0:
        return "ROBUST"
    if median >= 0.20:
        return "MARGINAL"
    return "OVERFIT"


def _verdict_badge(v: str) -> str:
    colour = {"ROBUST": "#16a34a", "MARGINAL": "#f59e0b",
              "OVERFIT": "#dc2626"}.get(v, "#6b7280")
    return (f"<span style='display:inline-block;padding:2px 10px;border-radius:10px;"
            f"background:{colour};color:white;font-weight:600;'>{v}</span>")


def _load(variant: str, outputs_root: Path) -> tuple[dict | None, pd.Series | None]:
    base = outputs_root / f"walkforward_{variant}"
    verdict_path = base / "walk_forward_verdict.json"
    eq_path = base / "equity_oos_concatenated.csv"
    verdict = None
    if verdict_path.exists():
        try:
            verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
        except Exception:
            verdict = None
    eq = None
    if eq_path.exists():
        try:
            df = pd.read_csv(eq_path, index_col=0, parse_dates=True)
            eq = df["equity_oos_eur"]
        except Exception:
            eq = None
    return verdict, eq


def build(variants: list[str], outputs_root: Path, out_html: Path) -> Path:
    rows = []
    equities: dict[str, pd.Series] = {}
    fold_table_rows: list[dict] = []

    for v in variants:
        verdict, eq = _load(v, outputs_root)
        if verdict is None:
            continue
        s = verdict["summary"]
        rows.append({
            "variant": v,
            "label": VARIANT_LABELS.get(v, v),
            "median_oos": s.get("median_sharpe_oos"),
            "p25_oos": s.get("p25_sharpe_oos"),
            "p75_oos": s.get("p75_sharpe_oos"),
            "n_folds": s.get("n_folds"),
            "verdict": s.get("verdict"),
        })
        if eq is not None:
            equities[v] = eq
        for f in verdict.get("folds", []):
            fold_table_rows.append({
                "variant": v,
                "fold": f["fold"],
                "test_window": f"{f['test_start']}..{f['test_end']}",
                "sharpe": f["sharpe"],
                "return_pct": f["total_return_pct"],
                "n_trades": f["n_trades"],
                "max_dd": f.get("max_drawdown"),
            })

    if not rows:
        raise RuntimeError("no variant outputs found — run scripts/run_quality_walk_forward.py "
                           "with --variant for each")

    summary_df = pd.DataFrame(rows)
    fold_df = pd.DataFrame(fold_table_rows)

    # ---- equity overlay ----
    fig_eq = go.Figure()
    for v, s in equities.items():
        fig_eq.add_trace(go.Scatter(
            x=s.index, y=s.values, mode="lines", name=VARIANT_LABELS.get(v, v),
            line=dict(width=2, color=PALETTE.get(v)),
        ))
    fig_eq.update_layout(template="plotly_white", height=420,
                         title="Concatenated OOS equity (5 folds chained)",
                         yaxis_title="EUR (from initial capital)",
                         legend=dict(orientation="h", y=-0.2))

    # ---- per-fold heatmap ----
    if not fold_df.empty:
        pivot = fold_df.pivot(index="variant", columns="fold", values="sharpe")
        # Preserve the variant order from the input
        pivot = pivot.reindex([v for v in variants if v in pivot.index])
        fig_hm = px.imshow(
            pivot.values,
            x=[f"Fold {c}" for c in pivot.columns],
            y=[VARIANT_LABELS.get(v, v) for v in pivot.index],
            color_continuous_scale="RdYlGn", aspect="auto",
            zmin=-2, zmax=2,
            text_auto=".2f",
        )
        fig_hm.update_layout(template="plotly_white", height=320,
                             title="OOS Sharpe per fold per variant",
                             xaxis_title="Fold", yaxis_title="Variant",
                             margin=dict(l=120, r=20, t=40, b=40))
    else:
        fig_hm = go.Figure()

    # ---- automatic recommendation ----
    robust = summary_df[summary_df["verdict"] == "ROBUST"].sort_values("median_oos", ascending=False)
    marginal = summary_df[summary_df["verdict"] == "MARGINAL"].sort_values("median_oos", ascending=False)
    if not robust.empty:
        top = robust.iloc[0]
        # tie-break by p25 (consistency)
        if len(robust) > 1:
            best_p25 = robust.sort_values("p25_oos", ascending=False).iloc[0]
            tie_note = ""
            if best_p25["variant"] != top["variant"]:
                tie_note = (f"<br><em>Note: {best_p25['variant']} has higher p25 "
                            f"({best_p25['p25_oos']:.3f}) than {top['variant']} "
                            f"({top['p25_oos']:.3f}) — more consistent across folds. "
                            f"Consider promoting {best_p25['variant']} for risk-control.</em>")
            else:
                tie_note = ""
        else:
            tie_note = ""
        rec = (f"<b>🟢 Promote <code>{top['variant']}</code> to recommended</b> — "
               f"median OOS Sharpe {top['median_oos']:+.3f}, p25 {top['p25_oos']:+.3f}.{tie_note}")
    elif not marginal.empty:
        top = marginal.iloc[0]
        rec = (f"<b>🟡 Consider <code>{top['variant']}</code> with caveat</b> — "
               f"median OOS Sharpe {top['median_oos']:+.3f} but p25 "
               f"{top['p25_oos']:+.3f} (one fold breaks down). Treat as exploratory.")
    else:
        rec = ("<b>🔴 No variant cleared the verdict thresholds.</b> Archive "
               "quality_stocks for now; focus on bonds + opportunistic sleeve.")

    # ---- summary table HTML ----
    fmt_summary = summary_df.copy()
    fmt_summary["verdict_badge"] = fmt_summary["verdict"].apply(_verdict_badge)
    for c in ("median_oos", "p25_oos", "p75_oos"):
        fmt_summary[c] = fmt_summary[c].apply(lambda x: f"{x:+.3f}" if pd.notna(x) else "n/a")
    summary_html = (
        "<table style='width:100%;border-collapse:collapse;font-family:sans-serif;'>"
        "<thead><tr style='background:#f3f4f6;text-align:left;'>"
        "<th style='padding:6px;'>Variant</th>"
        "<th style='padding:6px;'>Median OOS</th>"
        "<th style='padding:6px;'>p25</th>"
        "<th style='padding:6px;'>p75</th>"
        "<th style='padding:6px;'>Folds</th>"
        "<th style='padding:6px;'>Verdict</th>"
        "</tr></thead><tbody>"
    )
    for _, r in fmt_summary.iterrows():
        summary_html += (
            f"<tr style='border-top:1px solid #e5e7eb;'>"
            f"<td style='padding:6px;'><code>{r['variant']}</code><br>"
            f"<span style='color:#555;font-size:0.85em;'>{r['label']}</span></td>"
            f"<td style='padding:6px;'>{r['median_oos']}</td>"
            f"<td style='padding:6px;'>{r['p25_oos']}</td>"
            f"<td style='padding:6px;'>{r['p75_oos']}</td>"
            f"<td style='padding:6px;'>{r['n_folds']}</td>"
            f"<td style='padding:6px;'>{r['verdict_badge']}</td>"
            f"</tr>"
        )
    summary_html += "</tbody></table>"

    # ---- assemble HTML ----
    eq_html = fig_eq.to_html(include_plotlyjs="cdn", full_html=False, div_id="eq_chart")
    hm_html = fig_hm.to_html(include_plotlyjs=False, full_html=False, div_id="hm_chart")

    page = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8"/>
<title>Quality Stocks — Refinement Comparison</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 1200px; margin: 24px auto; padding: 0 16px; color: #1f2937; }}
  h1, h2 {{ border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; }}
  .recommendation {{ background:#f0f9ff; border-left:4px solid #2563eb;
                     padding:12px 16px; margin:20px 0; border-radius:4px; }}
  code {{ background:#f3f4f6; padding:1px 4px; border-radius:3px; }}
  .caveat {{ background:#fef3c7; border-left:4px solid #f59e0b;
             padding:12px 16px; margin:20px 0; border-radius:4px; font-size:0.95em; }}
</style></head>
<body>
<h1>Quality Stocks — Refinement Comparison</h1>
<p>5-variant walk-forward (5 folds each, train 4y / test 1y, 2016-01 → 2025-12).</p>

<div class="recommendation">
  <strong>Recommendation:</strong><br>
  {rec}
</div>

<div class="caveat">
  <strong>Statistical caveat:</strong> 5 folds is a small sample. The variants
  were chosen with prior knowledge of the baseline's per-fold weaknesses
  (notably the bond fallback in 2022), so there is residual confirmation bias.
  Real validation requires <em>new</em> data — either an out-of-window
  back-test (2014-2019 is currently un-tested), or live paper trading.
</div>

<h2>Summary</h2>
{summary_html}

<h2>Concatenated OOS equity curves</h2>
{eq_html}

<h2>Per-fold Sharpe heatmap</h2>
{hm_html}

<h2>Per-fold detail</h2>
{fold_df.to_html(index=False, escape=False) if not fold_df.empty else '<p>(no folds)</p>'}

<p style='color:#9ca3af;font-size:0.85em;margin-top:32px;'>
  Generated by <code>scripts/build_quality_refinement_comparison.py</code> —
  see <code>_migration_log/QUALITY_STOCKS_REFINEMENT_REPORT.md</code> for the
  full report.
</p>
</body></html>
"""

    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(page, encoding="utf-8")
    return out_html


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variants", nargs="+", default=DEFAULT_VARIANTS)
    ap.add_argument("--outputs-root", default=None,
                    help="default: outputs/quality_stocks/")
    ap.add_argument("--out", default=None,
                    help="default: outputs/quality_stocks/refinement_comparison.html")
    args = ap.parse_args(argv)

    outputs_root = Path(args.outputs_root) if args.outputs_root else (
        _REPO_ROOT / "outputs" / "quality_stocks"
    )
    out_html = Path(args.out) if args.out else (outputs_root / "refinement_comparison.html")

    p = build(args.variants, outputs_root, out_html)
    print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
