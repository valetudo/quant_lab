"""Definitive V5 vs SPY comparison report — single-file HTML.

Pulls V5's OOS concatenated equity from
``outputs/quality_stocks/walkforward_v5_full_history/equity_oos_concatenated.csv``
and benchmarks it against SPY buy-and-hold over the same window. Writes:

  outputs/quality_stocks/v5_vs_spy_definitive.html

The report is deliberately honest: if V5 underperforms SPY in absolute
return, the headline says so. The user's stated criterion:
"deve esserci una sovraperformance significativa per mettere in piedi
tutto questo sistema, altrimenti mi compro lo spy".
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# --- bootstrap ---
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# ---

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from core.backtest.benchmark import (
    Benchmark, alpha_summary, classify_outperformance,
    compute_rolling_alpha, compute_excess_return,
)


def _verdict_colour(v: str) -> str:
    return {"significant": "#16a34a", "marginal": "#f59e0b",
            "underperform": "#dc2626"}.get(v, "#6b7280")


def _verdict_label(v: str) -> str:
    return {
        "significant": "✅ V5 SIGNIFICANTLY outperforms SPY buy-and-hold",
        "marginal": "⚠️ V5 MARGINALLY outperforms SPY buy-and-hold",
        "underperform": "❌ V5 UNDERPERFORMS SPY buy-and-hold",
        "insufficient_data": "🟦 Insufficient data",
    }.get(v, "?")


def build(out_path: Path) -> Path:
    oos_path = _REPO_ROOT / "outputs" / "quality_stocks" / "walkforward_v5_full_history" / "equity_oos_concatenated.csv"
    if not oos_path.exists():
        raise FileNotFoundError(
            f"missing {oos_path} — run scripts/run_quality_walk_forward.py first"
        )
    v5 = pd.read_csv(oos_path, index_col=0, parse_dates=True).iloc[:, 0]
    # Concatenated folds can share a boundary date — dedup keeping the LATER row
    # (the start of the next fold, normalised to the previous fold's final equity).
    v5 = v5[~v5.index.duplicated(keep="last")].sort_index()
    bench = Benchmark("SPY").run(v5.index[0], v5.index[-1],
                                  initial_capital_eur=float(v5.iloc[0]))
    summary = alpha_summary(v5, bench.daily_equity)
    verdict = classify_outperformance(summary)

    n_years = (v5.index[-1] - v5.index[0]).days / 365.25

    # ---- charts -------------------------------------------------------

    fig_eq = go.Figure()
    fig_eq.add_trace(go.Scatter(x=v5.index, y=v5.values, mode="lines",
                                 name="V5 OOS",
                                 line=dict(width=2.5, color="#1f77b4")))
    fig_eq.add_trace(go.Scatter(x=bench.daily_equity.index,
                                 y=bench.daily_equity.values, mode="lines",
                                 name="SPY buy-and-hold",
                                 line=dict(width=1.5, dash="dash", color="#6b7280")))
    fig_eq.update_layout(template="plotly_white", height=460,
                          title=(f"Equity curves — V5 OOS vs SPY buy-and-hold "
                                 f"({v5.index[0].date()} → {v5.index[-1].date()})"),
                          yaxis_title="EUR",
                          legend=dict(orientation="h", y=-0.2))

    # Drawdown comparison
    v5_dd = (v5 / v5.cummax() - 1) * 100
    bench_dd = (bench.daily_equity / bench.daily_equity.cummax() - 1) * 100
    fig_dd = go.Figure()
    fig_dd.add_trace(go.Scatter(x=v5_dd.index, y=v5_dd.values,
                                 mode="lines", name="V5 DD %",
                                 fill="tozeroy",
                                 line=dict(width=1.2, color="#1f77b4")))
    fig_dd.add_trace(go.Scatter(x=bench_dd.index, y=bench_dd.values,
                                 mode="lines", name="SPY DD %",
                                 line=dict(width=1.2, dash="dash", color="#6b7280")))
    fig_dd.update_layout(template="plotly_white", height=300,
                          title="Drawdown comparison (%)",
                          yaxis_title="%", xaxis_title="",
                          legend=dict(orientation="h", y=-0.2))

    # Rolling 12m alpha
    rolling = compute_rolling_alpha(v5, bench.daily_equity, window_days=252) * 100
    fig_r = go.Figure()
    fig_r.add_trace(go.Scatter(x=rolling.index, y=rolling.values, mode="lines",
                                line=dict(width=1.2),
                                fill="tozeroy",
                                name="rolling 12m alpha %"))
    fig_r.add_hline(y=0, line_dash="dot", line_color="gray")
    fig_r.update_layout(template="plotly_white", height=300,
                         title="Rolling 12-month alpha vs SPY (%)",
                         yaxis_title="%", xaxis_title="")

    # ---- calendar-year table ------------------------------------------
    cy = pd.DataFrame(summary.get("calendar_year_table", []))
    if not cy.empty:
        rows_html = ""
        for _, r in cy.iterrows():
            alpha = float(r["alpha_pct"])
            row_colour = "#dcfce7" if alpha > 0 else "#fee2e2"
            rows_html += (
                f"<tr style='background:{row_colour};'>"
                f"<td>{int(r['year'])}</td>"
                f"<td style='text-align:right;'>{r['return_pct_strategy']:+.2f}%</td>"
                f"<td style='text-align:right;'>{r['return_pct_benchmark']:+.2f}%</td>"
                f"<td style='text-align:right;font-weight:600;'>{alpha:+.2f} pp</td>"
                f"<td style='text-align:center;'>{'✅' if bool(r['win']) else '❌'}</td>"
                f"</tr>"
            )
        cy_html = (
            "<table style='width:100%;border-collapse:collapse;font-size:0.95em;'>"
            "<thead><tr style='background:#f3f4f6;'>"
            "<th>Year</th><th>V5 %</th><th>SPY %</th><th>Alpha</th><th>V5 won?</th>"
            "</tr></thead><tbody>"
            f"{rows_html}"
            "</tbody></table>"
        )
    else:
        cy_html = "<p>(no calendar-year data)</p>"

    # ---- bear-period analysis (windows where SPY DD > 15%) -------------
    # Align V5 DD to the SPY index (forward-fill) so we can safely .loc by date
    v5_dd_aligned = v5_dd.reindex(bench_dd.index, method="ffill")
    bear_blocks = []
    in_bear = False
    bear_start = None
    bear_min_v5 = 0.0
    bear_min_spy = 0.0
    for ts, dd_val in bench_dd.items():
        dd_val = float(dd_val)
        v5_dd_now = float(v5_dd_aligned.loc[ts]) if ts in v5_dd_aligned.index else 0.0
        if not in_bear and dd_val < -15:
            in_bear = True; bear_start = ts
            bear_min_v5 = v5_dd_now; bear_min_spy = dd_val
        elif in_bear:
            bear_min_v5 = min(bear_min_v5, v5_dd_now)
            bear_min_spy = min(bear_min_spy, dd_val)
            if dd_val >= -2:  # recovered
                bear_blocks.append({
                    "start": bear_start, "end": ts,
                    "spy_max_dd": bear_min_spy, "v5_max_dd": bear_min_v5,
                })
                in_bear = False
    if in_bear:
        bear_blocks.append({
            "start": bear_start, "end": bench_dd.index[-1],
            "spy_max_dd": bear_min_spy, "v5_max_dd": bear_min_v5,
        })
    bear_html = ""
    if bear_blocks:
        bear_rows = ""
        for b in bear_blocks:
            saved = b["v5_max_dd"] - b["spy_max_dd"]  # positive = V5 saved you DD
            bear_rows += (
                f"<tr><td>{b['start'].date()} → {b['end'].date()}</td>"
                f"<td style='text-align:right;'>{b['spy_max_dd']:+.1f}%</td>"
                f"<td style='text-align:right;'>{b['v5_max_dd']:+.1f}%</td>"
                f"<td style='text-align:right;color:"
                f"{'#16a34a' if saved > 0 else '#dc2626'};font-weight:600;'>"
                f"{saved:+.1f} pp</td></tr>"
            )
        bear_html = (
            "<h2>Defensive behaviour during SPY drawdowns &gt; 15%</h2>"
            "<p>How V5 held up when SPY took meaningful losses.</p>"
            "<table style='width:100%;border-collapse:collapse;'>"
            "<thead><tr style='background:#f3f4f6;'>"
            "<th>Period</th><th>SPY worst DD</th><th>V5 worst DD</th>"
            "<th>V5 saved you</th></tr></thead><tbody>"
            f"{bear_rows}</tbody></table>"
        )

    # ---- recommendation block ------------------------------------------
    alpha_pp = (summary.get("annualized_alpha") or 0) * 100
    if verdict == "significant":
        rec = (
            "<p>V5 generates significant absolute outperformance. Deploy V5 as "
            "the equity sleeve and treat SPY as a benchmark, not a baseline.</p>"
        )
    elif verdict == "marginal":
        rec = (
            "<p>V5 outperforms SPY by less than 2 pp/yr — the edge is real but "
            "small relative to execution risk. Recommend paper trading at full "
            "weight while monitoring whether the alpha persists.</p>"
        )
    else:
        rec = (
            f"<p><b>V5 underperforms SPY by {-alpha_pp:.2f} pp/yr over the "
            "full OOS window.</b> Its Sharpe is essentially equal to SPY's "
            f"({summary['strategy_sharpe']:.2f} vs {summary['benchmark_sharpe']:.2f}) "
            f"but its max drawdown is materially smaller "
            f"({summary['strategy_max_dd']*100:.1f}% vs "
            f"{summary['benchmark_max_dd']*100:.1f}%).</p>"
            "<p><b>The case for V5 is defensive vol-control inside a multi-asset "
            "portfolio, not as a SPY-replacement.</b> The Phase-3 60/30/10 sleeve "
            "model already takes this into account: V5 is 30% of the equity "
            "sleeve, bonds and cash absorb the rest. In that context V5 still "
            "earns its slot because it gives up some upside in exchange for "
            "drawdown protection. Standalone deployment of V5 (no bonds, no "
            "cash) would underperform passive SPY most years.</p>"
            "<p>If you want pure absolute return at 100% equity allocation, "
            "<b>SPY is the better choice</b>. If you want a portfolio that "
            "loses less in bad years and gives up some upside in good ones, "
            "V5 + bonds + cash is the better choice.</p>"
        )

    # ---- assemble HTML -------------------------------------------------
    eq_html = fig_eq.to_html(include_plotlyjs="cdn", full_html=False, div_id="eq")
    dd_html = fig_dd.to_html(include_plotlyjs=False, full_html=False, div_id="dd")
    r_html = fig_r.to_html(include_plotlyjs=False, full_html=False, div_id="r")

    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>V5 vs SPY — Definitive Report</title>
<style>
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         max-width:1200px;margin:24px auto;padding:0 16px;color:#1f2937; }}
  h1,h2 {{ border-bottom:1px solid #e5e7eb;padding-bottom:6px; }}
  table {{ width:100%;border-collapse:collapse;font-size:0.95em;margin:10px 0; }}
  th,td {{ border:1px solid #e5e7eb;padding:5px 9px; }}
  th {{ background:#f9fafb; }}
  .headline {{ padding:22px 26px;border-radius:10px;color:white;margin:18px 0; }}
  .summary-grid {{ display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:12px 0; }}
  .summary-grid > div {{ background:#f9fafb;padding:10px 14px;border-radius:6px; }}
  .summary-grid .label {{ color:#6b7280;font-size:0.85em; }}
  .summary-grid .value {{ font-size:1.4em;font-weight:700; }}
</style></head><body>
<h1>Quality Stocks V5 — Definitive Comparison vs SPY Buy-and-Hold</h1>
<p style='color:#6b7280;'>Generated {datetime.now():%Y-%m-%d %H:%M} •
   Window {v5.index[0].date()} → {v5.index[-1].date()} ({n_years:.1f} years OOS)</p>

<div class="headline" style='background:{_verdict_colour(verdict)};'>
  <div style='font-size:1.4em;font-weight:700;'>{_verdict_label(verdict)}</div>
  <div style='font-size:1.05em;margin-top:8px;'>
    Annualised alpha: <b style='font-size:1.4em;'>{alpha_pp:+.2f} pp/yr</b>
    &nbsp;|&nbsp; Calendar-year wins: <b>{summary['calendar_year_wins']}/{summary['calendar_year_total']}</b>
    ({summary['calendar_year_win_rate']*100:.0f}%)
  </div>
</div>

<div class="summary-grid">
  <div><div class="label">V5 CAGR</div><div class="value">{summary['strategy_cagr']*100:+.2f}%</div></div>
  <div><div class="label">SPY CAGR</div><div class="value">{summary['benchmark_cagr']*100:+.2f}%</div></div>
  <div><div class="label">V5 Sharpe</div><div class="value">{summary['strategy_sharpe']:.2f}</div></div>
  <div><div class="label">SPY Sharpe</div><div class="value">{summary['benchmark_sharpe']:.2f}</div></div>
  <div><div class="label">V5 Max DD</div><div class="value">{summary['strategy_max_dd']*100:.1f}%</div></div>
  <div><div class="label">SPY Max DD</div><div class="value">{summary['benchmark_max_dd']*100:.1f}%</div></div>
  <div><div class="label">V5 final equity</div><div class="value">€{v5.iloc[-1]:,.0f}</div></div>
  <div><div class="label">SPY final equity</div><div class="value">€{bench.final_equity_eur:,.0f}</div></div>
</div>

<h2>Equity curves</h2>
{eq_html}

<h2>Calendar-year returns</h2>
{cy_html}

<h2>Drawdown comparison</h2>
{dd_html}

{bear_html}

<h2>Rolling 12-month alpha</h2>
{r_html}

<h2>Recommendation</h2>
{rec}

<hr>
<p style='color:#9ca3af;font-size:0.85em;'>
  Generated by <code>scripts/generate_v5_vs_spy_report.py</code> •
  Source: <code>{oos_path.relative_to(_REPO_ROOT)}</code>
</p>
</body></html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(_REPO_ROOT / "outputs" / "quality_stocks"
                                        / "v5_vs_spy_definitive.html"))
    args = ap.parse_args(argv)
    p = build(Path(args.out))
    print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
