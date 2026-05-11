"""Side-by-side comparison of V5 with and without survivorship correction.

Reads:
  outputs/quality_stocks/walkforward_v5_full_history/walk_forward_verdict_extended.json
  outputs/quality_stocks/walkforward_v5_full_history/equity_oos_concatenated.csv
  outputs/quality_stocks/walkforward_v5_holdout/walk_forward_verdict_extended.json
  outputs/quality_stocks/walkforward_v5_survivorship_full/walk_forward_verdict_extended.json
  outputs/quality_stocks/walkforward_v5_survivorship_full/equity_oos_concatenated.csv
  outputs/quality_stocks/walkforward_v5_survivorship_holdout/walk_forward_verdict_extended.json

Writes:
  outputs/quality_stocks/survivorship_comparison.html
  outputs/quality_stocks/survivorship_comparison.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# --- bootstrap ---
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# ---

import pandas as pd
import plotly.graph_objects as go


def _load_summary(variant_dir: Path) -> dict:
    p = variant_dir / "walk_forward_verdict_extended.json"
    if not p.exists():
        p = variant_dir / "walk_forward_verdict.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _safe(d: dict, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _verdict_badge_html(v: str | None) -> str:
    colour = {"ROBUST": "#16a34a", "MARGINAL": "#f59e0b",
              "OVERFIT": "#dc2626"}.get(v or "", "#6b7280")
    return (f"<span style='display:inline-block;padding:2px 10px;border-radius:10px;"
            f"background:{colour};color:white;font-weight:600;font-size:0.9em;'>"
            f"{v or '?'}</span>")


def _delta_cell(uncorr: float | None, corr: float | None, fmt: str = "{:+.3f}",
                 lower_is_worse: bool = True) -> str:
    if uncorr is None or corr is None:
        return "<td>—</td><td>—</td><td>—</td>"
    delta = corr - uncorr
    if lower_is_worse:
        col = "#16a34a" if delta >= 0 else "#dc2626"
    else:
        col = "#dc2626" if delta >= 0 else "#16a34a"
    return (f"<td>{fmt.format(uncorr)}</td>"
            f"<td>{fmt.format(corr)}</td>"
            f"<td style='color:{col};font-weight:600;'>{fmt.format(delta)}</td>")


def build(output_root: Path) -> dict:
    uncorr_full = _load_summary(output_root / "walkforward_v5_full_history")
    uncorr_ho   = _load_summary(output_root / "walkforward_v5_holdout")
    corr_full   = _load_summary(output_root / "walkforward_v5_survivorship_full")
    corr_ho     = _load_summary(output_root / "walkforward_v5_survivorship_holdout")
    boot_uncorr = json.loads(((_REPO_ROOT / "outputs" / "validation"
                                / "v5_statistical_significance.json").read_text(encoding="utf-8"))) if (
        _REPO_ROOT / "outputs" / "validation" / "v5_statistical_significance.json").exists() else {}
    boot_corr   = json.loads(((_REPO_ROOT / "outputs" / "validation"
                                / "v5_survivorship_statistical_significance.json").read_text(encoding="utf-8"))) if (
        _REPO_ROOT / "outputs" / "validation" / "v5_survivorship_statistical_significance.json").exists() else {}

    rows: list[dict] = []
    for label, key, default_fmt, lower_worse in [
        ("Folds (n)", lambda x: _safe(x, "summary", "n_folds"), "{:.0f}", False),
        ("Sharpe obs (n)", lambda x: _safe(x, "summary", "n_sharpe_observations"), "{:.0f}", False),
        ("Median OOS Sharpe", lambda x: _safe(x, "summary", "median_oos_sharpe"), "{:+.3f}", True),
        ("Mean OOS Sharpe", lambda x: _safe(x, "summary", "mean_oos_sharpe"), "{:+.3f}", True),
        ("p25 OOS Sharpe", lambda x: _safe(x, "summary", "p25_oos_sharpe"), "{:+.3f}", True),
        ("p75 OOS Sharpe", lambda x: _safe(x, "summary", "p75_oos_sharpe"), "{:+.3f}", True),
        ("Hit-rate > 0", lambda x: _safe(x, "summary", "hit_rate_positive"), "{:.0%}", True),
        ("Hit-rate > 0.5", lambda x: _safe(x, "summary", "hit_rate_above_0_5"), "{:.0%}", True),
        ("t-stat vs 0", lambda x: _safe(x, "summary", "t_stat_vs_zero"), "{:+.2f}", True),
        ("p-value vs 0", lambda x: _safe(x, "summary", "p_value_vs_zero"), "{:.4f}", False),
    ]:
        u_full = key(uncorr_full); c_full = key(corr_full)
        u_ho = key(uncorr_ho); c_ho = key(corr_ho)
        rows.append({
            "metric": label,
            "uncorr_full": u_full, "corr_full": c_full,
            "uncorr_ho": u_ho, "corr_ho": c_ho,
            "fmt": default_fmt, "lower_worse": lower_worse,
        })

    # Bootstrap CI
    rows.append({
        "metric": "Bootstrap CI lower (95%)",
        "uncorr_full": _safe(boot_uncorr, "ci_lower_2_5pct"),
        "corr_full": _safe(boot_corr, "ci_lower_2_5pct"),
        "uncorr_ho": None, "corr_ho": None,
        "fmt": "{:+.3f}", "lower_worse": True,
    })

    # Build the HTML comparison table
    table_html = (
        "<table><thead><tr style='background:#f3f4f6;'>"
        "<th rowspan='2'>Metric</th>"
        "<th colspan='3' style='text-align:center;background:#eff6ff;'>Full history</th>"
        "<th colspan='3' style='text-align:center;background:#fef3c7;'>Hold-out (2012-2019)</th>"
        "</tr><tr style='background:#f3f4f6;'>"
        "<th>uncorrected</th><th>corrected</th><th>Δ</th>"
        "<th>uncorrected</th><th>corrected</th><th>Δ</th>"
        "</tr></thead><tbody>"
    )
    for r in rows:
        full_cells = _delta_cell(r["uncorr_full"], r["corr_full"], r["fmt"],
                                  lower_is_worse=r["lower_worse"])
        ho_cells = _delta_cell(r["uncorr_ho"], r["corr_ho"], r["fmt"],
                                lower_is_worse=r["lower_worse"])
        table_html += f"<tr><td><b>{r['metric']}</b></td>{full_cells}{ho_cells}</tr>"
    table_html += "</tbody></table>"

    # Verdict badges
    verdict_row = ""
    for label, src in [("Full history V2.3 verdict", "summary"),
                        ("Full history (legacy verdict)", "summary")]:
        pass  # placeholder
    verdict_row = (
        f"<p>Full-history V2.3 verdict: uncorrected = "
        f"{_verdict_badge_html(_safe(uncorr_full, 'summary', 'verdict_v23'))}, "
        f"corrected = {_verdict_badge_html(_safe(corr_full, 'summary', 'verdict_v23'))}<br>"
        f"Hold-out V2.3 verdict: uncorrected = "
        f"{_verdict_badge_html(_safe(uncorr_ho, 'summary', 'verdict_v23'))}, "
        f"corrected = {_verdict_badge_html(_safe(corr_ho, 'summary', 'verdict_v23'))}</p>"
    )

    # Equity overlay chart (full-history concatenated)
    eq_html = ""
    fig = go.Figure()
    for label, sub, colour in [
        ("V5 uncorrected (current SP500 universe)",
         output_root / "walkforward_v5_full_history" / "equity_oos_concatenated.csv",
         "#1f77b4"),
        ("V5 survivorship-corrected (point-in-time universe)",
         output_root / "walkforward_v5_survivorship_full" / "equity_oos_concatenated.csv",
         "#dc2626"),
    ]:
        if not sub.exists():
            continue
        df = pd.read_csv(sub, index_col=0, parse_dates=True)
        s = df.iloc[:, 0]
        fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines", name=label,
                                  line=dict(width=2, color=colour)))
    fig.update_layout(template="plotly_white", height=420,
                       title="OOS concatenated equity — V5 uncorrected vs survivorship-corrected",
                       yaxis_title="EUR")
    eq_html = fig.to_html(include_plotlyjs="cdn", full_html=False)

    # Per-fold Sharpe bar chart
    fold_uncorr = _safe(uncorr_full, "folds", default=[])
    fold_corr = _safe(corr_full, "folds", default=[])
    if fold_uncorr and fold_corr:
        years = [f["test_start"][:4] for f in fold_uncorr]
        u_sh = [f["sharpe"] or 0 for f in fold_uncorr]
        c_sh = [f["sharpe"] or 0 for f in fold_corr]
        fig_b = go.Figure()
        fig_b.add_trace(go.Bar(x=years, y=u_sh, name="uncorrected",
                                marker_color="#1f77b4"))
        fig_b.add_trace(go.Bar(x=years, y=c_sh, name="corrected",
                                marker_color="#dc2626"))
        fig_b.add_hline(y=0, line_dash="dot", line_color="gray")
        fig_b.update_layout(template="plotly_white", height=320, barmode="group",
                            title="Per-fold OOS Sharpe — uncorrected vs corrected",
                            yaxis_title="Sharpe", xaxis_title="OOS year")
        bar_html = fig_b.to_html(include_plotlyjs=False, full_html=False)
    else:
        bar_html = ""

    # Interpretation block
    u_med = _safe(uncorr_full, "summary", "median_oos_sharpe")
    c_med = _safe(corr_full, "summary", "median_oos_sharpe")
    if u_med is not None and c_med is not None:
        delta_med = c_med - u_med
        if delta_med >= -0.10:
            verdict_block = (
                "<div style='background:#dcfce7;border-left:4px solid #16a34a;padding:12px 16px;'>"
                f"<b>✅ Scenario A — survivorship bias was minimal.</b> "
                f"Median Sharpe drops only {-delta_med:+.3f} (corrected {c_med:+.3f} vs "
                f"uncorrected {u_med:+.3f}). V5's edge is largely real."
                "</div>"
            )
        elif delta_med >= -0.30:
            verdict_block = (
                "<div style='background:#fef3c7;border-left:4px solid #f59e0b;padding:12px 16px;'>"
                f"<b>🟡 Scenario B — measurable but non-destructive bias.</b> "
                f"Median Sharpe drops {-delta_med:+.3f} (corrected {c_med:+.3f} vs "
                f"uncorrected {u_med:+.3f}). V5 still has edge but expectations "
                "for forward Sharpe should be lower than the headline number."
                "</div>"
            )
        else:
            verdict_block = (
                "<div style='background:#fef2f2;border-left:4px solid #dc2626;padding:12px 16px;'>"
                f"<b>🔴 Scenario C — survivorship was the main driver.</b> "
                f"Median Sharpe drops {-delta_med:+.3f} (corrected {c_med:+.3f} vs "
                f"uncorrected {u_med:+.3f}). The strategy relied on knowing "
                "which names would survive. Do NOT deploy."
                "</div>"
            )
    else:
        verdict_block = "<p>Insufficient data to render scenario verdict.</p>"

    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>V5 Survivorship Comparison</title>
<style>
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         max-width:1200px;margin:24px auto;padding:0 16px;color:#1f2937; }}
  h1,h2 {{ border-bottom:1px solid #e5e7eb;padding-bottom:6px; }}
  table {{ width:100%;border-collapse:collapse;font-size:0.9em;margin:12px 0; }}
  th,td {{ border:1px solid #e5e7eb;padding:5px 9px;text-align:left; }}
  th {{ background:#f9fafb; }}
</style></head><body>
<h1>V5 — Survivorship-correction Comparison</h1>
<p>Side-by-side: original V5 (current SP500 universe) vs survivorship-corrected V5
(point-in-time S&P 500 membership reconstructed from FMP's
<code>/historical-sp500-constituent</code> change log).</p>

{verdict_block}

<h2>Verdict summary</h2>
{verdict_row}

<h2>Side-by-side metrics</h2>
{table_html}

<h2>OOS equity overlay</h2>
{eq_html}

<h2>Per-fold Sharpe</h2>
{bar_html}

<h2>Notes</h2>
<ul>
  <li><b>Universe coverage limitation</b>: only ~74% of the historical universe
      has price data in the local cache. Tickers that were delisted before
      today are excluded entirely from the corrected backtest. The correction
      therefore removes <em>lookahead</em> bias (future winners are no longer
      pre-included) but does NOT add the losers back into the universe. The
      true "full survivorship correction" would require fetching prices for
      323 delisted tickers — a Phase 4 task.</li>
  <li>V5 parameters are <b>frozen</b> — the only change between uncorrected
      and corrected is the universe selection logic.</li>
</ul>
</body></html>"""

    out_html = output_root / "survivorship_comparison.html"
    out_html.write_text(page, encoding="utf-8")
    out_json = output_root / "survivorship_comparison.json"
    out_json.write_text(json.dumps({
        "uncorrected_full": uncorr_full.get("summary", {}),
        "corrected_full": corr_full.get("summary", {}),
        "uncorrected_holdout": uncorr_ho.get("summary", {}),
        "corrected_holdout": corr_ho.get("summary", {}),
        "delta_full_median": (c_med - u_med) if (u_med is not None and c_med is not None) else None,
    }, indent=2, default=str), encoding="utf-8")
    return {"html": out_html, "json": out_json}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-root", default=str(_REPO_ROOT / "outputs" / "quality_stocks"))
    args = ap.parse_args(argv)
    out = build(Path(args.output_root))
    print(f"HTML: {out['html']}")
    print(f"JSON: {out['json']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
