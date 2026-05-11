"""Compare 5 passive equity-sleeve allocations over a fixed 13-year window.

Output:
  outputs/equity_comparison/comparison.html        — single-file standalone report
  outputs/equity_comparison/metrics_table.csv      — definitive metrics table
  outputs/equity_comparison/equity_curves.csv      — daily equity per allocation
  outputs/equity_comparison/annual_returns.csv     — year × allocation matrix

This is a DESCRIPTIVE comparison, not an optimisation. The 5 allocations were
specified exogenously by the user; the script doesn't pick a winner — it just
shows the trade-offs.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# --- bootstrap ---
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# ---

import pandas as pd
import plotly.graph_objects as go

from core.backtest.passive_portfolio import PassivePortfolio, PassivePortfolioResult

ALLOCATIONS = [
    ("SPY_pure", "100% SPY buy-and-hold", {"SPY": 1.0}, "none"),
    (
        "Heavy_Staples",
        "50% XLP + 5% × 10 other sectors",
        {
            "XLP": 0.50,
            "XLK": 0.05,
            "XLV": 0.05,
            "XLF": 0.05,
            "XLY": 0.05,
            "XLC": 0.05,
            "XLI": 0.05,
            "XLE": 0.05,
            "XLB": 0.05,
            "XLU": 0.05,
            "XLRE": 0.05,
        },
        "quarterly",
    ),
    (
        "Equal_Weight_Sectors",
        "~9.09% in each of 11 sectors",
        {
            s: 1 / 11
            for s in ("XLP", "XLK", "XLV", "XLF", "XLY", "XLC", "XLI", "XLE", "XLB", "XLU", "XLRE")
        },
        "quarterly",
    ),
    (
        "Defensive_Barbell",
        "60% SPY + 40% defensive (XLP/XLV/XLU equally)",
        {"SPY": 0.60, "XLP": 0.40 / 3, "XLV": 0.40 / 3, "XLU": 0.40 - 2 * (0.40 / 3)},
        "quarterly",
    ),
    ("RSP_equal_weight", "100% RSP (Invesco S&P 500 Equal Weight ETF)", {"RSP": 1.0}, "none"),
]

START = "2012-01-03"
END = "2025-01-01"
INITIAL_CAPITAL = 100_000.0
PALETTE = ["#1f77b4", "#dc2626", "#16a34a", "#f59e0b", "#7c3aed"]


def _metrics_row(r: PassivePortfolioResult) -> dict:
    return {
        "Allocation": r.name,
        "CAGR_pct": r.cagr * 100,
        "Sharpe": r.sharpe,
        "Sortino": r.sortino,
        "MaxDD_pct": r.max_drawdown * 100,
        "Calmar": r.calmar,
        "AnnVol_pct": r.annualized_vol * 100,
        "TotalReturn_pct": r.total_return_pct,
        "FinalEquity_EUR": r.final_equity_eur,
        "TotalSlippage_EUR": r.total_slippage_cost_eur,
        "Rebalances": (
            len(r.rebalance_events)
            if r.rebalance_events is not None and not r.rebalance_events.empty
            else 0
        ),
    }


def _annual_matrix(results: list[PassivePortfolioResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        for _, row in r.annual_returns.iterrows():
            rows.append(
                {"year": int(row["year"]), "alloc": r.name, "return_pct": float(row["return_pct"])}
            )
    df = pd.DataFrame(rows)
    pivot = df.pivot(index="year", columns="alloc", values="return_pct")
    # Preserve allocation order
    cols = [r.name for r in results if r.name in pivot.columns]
    return pivot[cols]


# ---- bear / bull period detection on SPY ---------------------------------


def _spy_bear_periods(spy_eq: pd.Series, threshold_pct: float = -15.0) -> list[dict]:
    rm = spy_eq.cummax()
    dd = (spy_eq / rm - 1.0) * 100
    blocks = []
    in_bear = False
    bstart = None
    bmin = 0.0
    for ts, dd_val in dd.items():
        dd_val = float(dd_val)
        if not in_bear and dd_val < threshold_pct:
            in_bear = True
            bstart = ts
            bmin = dd_val
        elif in_bear:
            bmin = min(bmin, dd_val)
            if dd_val >= -2:  # recovered to within 2% of peak
                blocks.append({"start": bstart, "end": ts, "spy_max_dd": bmin})
                in_bear = False
    if in_bear:
        blocks.append({"start": bstart, "end": dd.index[-1], "spy_max_dd": bmin})
    return blocks


def _max_dd_in_window(eq: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> float:
    sub = eq[(eq.index >= start) & (eq.index <= end)]
    if sub.empty:
        return 0.0
    rm = sub.cummax()
    return float((sub / rm - 1.0).min() * 100)


# ---- HTML rendering ------------------------------------------------------


def _color_cell(value: float, best: float, worst: float, higher_is_better: bool) -> str:
    """Background colour for a metric cell — gradient red→green."""
    if pd.isna(value):
        return "background:#f9fafb;"
    if best == worst:
        return "background:#f9fafb;"
    span = best - worst
    norm = (value - worst) / span if higher_is_better else 1 - (value - worst) / span
    norm = max(0.0, min(1.0, norm))
    # Interpolate red (220,38,38) -> green (22,163,74) through yellow
    if norm < 0.5:
        r = 220
        g = int(38 + (255 - 38) * (norm * 2))
        b = 38
    else:
        r = int(220 - (220 - 22) * ((norm - 0.5) * 2))
        g = int(255 - (255 - 163) * ((norm - 0.5) * 2))
        b = int(38 + (74 - 38) * ((norm - 0.5) * 2))
    return f"background:rgb({r},{g},{b});color:white;font-weight:600;"


def _calendar_year_cell_colour(value: float) -> str:
    """Continuous red→green colour scale for cell backgrounds."""
    if pd.isna(value):
        return ""
    v = max(-30, min(40, float(value)))
    # red for negative, green for positive, intensity proportional to magnitude
    if v < 0:
        intensity = min(1.0, abs(v) / 30.0)
        r = int(254 - 30 * intensity)
        g = int(226 - 100 * intensity)
        b = int(226 - 100 * intensity)
    else:
        intensity = min(1.0, v / 40.0)
        r = int(220 - 80 * intensity)
        g = int(252 - 30 * intensity)
        b = int(231 - 80 * intensity)
    return f"background:rgb({r},{g},{b});"


def render_html(results: list[PassivePortfolioResult], out_path: Path) -> Path:
    metrics = pd.DataFrame([_metrics_row(r) for r in results])

    # --- 5.1 — Winners ----------------------------------------------------
    winners = {
        "Total Return / CAGR": metrics.loc[metrics["CAGR_pct"].idxmax(), "Allocation"],
        "Sharpe": metrics.loc[metrics["Sharpe"].idxmax(), "Allocation"],
        "Lowest Max DD": metrics.loc[metrics["MaxDD_pct"].idxmax(), "Allocation"],  # least-negative
        "Calmar": metrics.loc[metrics["Calmar"].idxmax(), "Allocation"],
        "Final Equity": metrics.loc[metrics["FinalEquity_EUR"].idxmax(), "Allocation"],
    }
    headline_rows = ""
    for k, v in winners.items():
        winner_val = None
        if "Total" in k or "CAGR" in k:
            winner_val = f"CAGR +{metrics['CAGR_pct'].max():.2f}%"
        elif "Sharpe" in k:
            winner_val = f"Sharpe {metrics['Sharpe'].max():.2f}"
        elif "Lowest" in k:
            winner_val = f"Max DD {metrics['MaxDD_pct'].max():+.2f}%"
        elif "Calmar" in k:
            winner_val = f"Calmar {metrics['Calmar'].max():.2f}"
        else:
            winner_val = f"Final €{metrics['FinalEquity_EUR'].max():,.0f}"
        headline_rows += (
            f"<tr><td style='padding:6px 12px;'><b>#1 by {k}:</b></td>"
            f"<td style='padding:6px 12px;color:#16a34a;'>"
            f"<b>{v}</b></td><td style='padding:6px 12px;color:#555;'>"
            f"{winner_val}</td></tr>"
        )
    headline_html = f"""
<div style='padding:18px 22px;border-radius:10px;background:#1f2937;
            color:white;margin:18px 0;'>
<div style='font-size:1.05em;font-weight:700;margin-bottom:8px;'>
  Window: 2012-01-03 → 2025-01-01 ({(pd.to_datetime(END) - pd.to_datetime(START)).days / 365.25:.1f} years)
   •  Initial capital: €100,000
</div>
<table style='color:white;'>
<tbody>{headline_rows}</tbody>
</table>
</div>
"""

    # --- 5.2 — Definitive metrics table ----------------------------------
    metric_specs = [
        ("CAGR_pct", "{:+.2f}%", True),
        ("Sharpe", "{:.2f}", True),
        ("Sortino", "{:.2f}", True),
        ("MaxDD_pct", "{:+.2f}%", True),  # less negative is better, idxmax works
        ("Calmar", "{:.2f}", True),
        ("AnnVol_pct", "{:.2f}%", False),  # lower vol is better
        ("FinalEquity_EUR", "€{:,.0f}", True),
    ]
    rows_html = ""
    for _, r in metrics.iterrows():
        cells = [f"<td><b>{r['Allocation']}</b></td>"]
        for col, fmt, higher in metric_specs:
            value = float(r[col])
            best = metrics[col].max() if higher else metrics[col].min()
            worst = metrics[col].min() if higher else metrics[col].max()
            style = _color_cell(value, best, worst, higher_is_better=higher)
            cells.append(
                f"<td style='{style}padding:6px 10px;text-align:right;'>{fmt.format(value)}</td>"
            )
        rows_html += "<tr>" + "".join(cells) + "</tr>"
    headers = (
        "Allocation",
        "CAGR",
        "Sharpe",
        "Sortino",
        "Max DD",
        "Calmar",
        "Ann Vol",
        "Final from €100k",
    )
    head_html = (
        "<tr style='background:#f3f4f6;'>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>"
    )
    table_html = (
        f"<h2>Metrics — side by side</h2>"
        f"<table style='width:100%;border-collapse:collapse;font-size:0.95em;'>"
        f"<thead>{head_html}</thead><tbody>{rows_html}</tbody></table>"
        f"<p style='color:#555;font-size:0.85em;'>Cell colour: red worst → green best per column. "
        f"Annual vol is treated as lower-is-better.</p>"
    )

    # --- 5.3 — Equity overlay --------------------------------------------
    fig_eq = go.Figure()
    for r, c in zip(results, PALETTE):
        fig_eq.add_trace(
            go.Scatter(
                x=r.daily_equity.index,
                y=r.daily_equity.values,
                mode="lines",
                name=r.name,
                line=dict(width=2.0, color=c),
            )
        )
    fig_eq.add_hline(y=INITIAL_CAPITAL, line_dash="dot", line_color="#cbd5e1")
    fig_eq.update_layout(
        template="plotly_white",
        height=480,
        title="Equity curves — 5 allocations on €100k initial",
        yaxis_title="EUR",
        legend=dict(orientation="h", y=-0.18),
    )
    eq_html = fig_eq.to_html(include_plotlyjs="cdn", full_html=False, div_id="eq")

    # --- 5.4 — Drawdown comparison ---------------------------------------
    fig_dd = go.Figure()
    for r, c in zip(results, PALETTE):
        rm = r.daily_equity.cummax()
        dd = (r.daily_equity / rm - 1.0) * 100
        fig_dd.add_trace(
            go.Scatter(
                x=dd.index,
                y=dd.values,
                mode="lines",
                name=r.name,
                line=dict(width=1.5, color=c),
            )
        )
    fig_dd.add_hline(y=0, line_dash="dot", line_color="gray")
    fig_dd.update_layout(
        template="plotly_white",
        height=380,
        title="Drawdown % comparison",
        yaxis_title="%",
        legend=dict(orientation="h", y=-0.2),
    )
    dd_html = fig_dd.to_html(include_plotlyjs=False, full_html=False, div_id="dd")

    # --- 5.5 — Calendar year returns ------------------------------------
    annual_pivot = _annual_matrix(results)
    cy_rows_html = ""
    wins_per_alloc = {r.name: 0 for r in results}
    for year, row in annual_pivot.iterrows():
        winning_alloc = row.idxmax()
        wins_per_alloc[winning_alloc] += 1
        cells = [f"<td><b>{int(year)}</b></td>"]
        for alloc in annual_pivot.columns:
            v = float(row[alloc])
            style = _calendar_year_cell_colour(v)
            if alloc == winning_alloc:
                style += "outline:2px solid #16a34a;font-weight:700;"
            cells.append(f"<td style='{style}padding:5px 10px;text-align:right;'>{v:+.2f}%</td>")
        cy_rows_html += "<tr>" + "".join(cells) + "</tr>"
    # Totals row
    total_cells = ["<td style='font-weight:700;'>WINS</td>"]
    for alloc in annual_pivot.columns:
        total_cells.append(
            f"<td style='padding:5px 10px;text-align:right;"
            f"font-weight:700;background:#f3f4f6;'>"
            f"{wins_per_alloc[alloc]}/{len(annual_pivot)}</td>"
        )
    cy_rows_html += "<tr>" + "".join(total_cells) + "</tr>"
    cy_head = (
        "<tr style='background:#f3f4f6;'><th>Year</th>"
        + "".join(f"<th>{c}</th>" for c in annual_pivot.columns)
        + "</tr>"
    )
    cy_html = (
        f"<h2>Calendar-year returns</h2>"
        f"<table style='width:100%;border-collapse:collapse;font-size:0.9em;'>"
        f"<thead>{cy_head}</thead><tbody>{cy_rows_html}</tbody></table>"
        f"<p style='color:#555;font-size:0.85em;'>Outlined cell = winner that "
        f"year. Bottom row totals how many years each allocation won.</p>"
    )

    # --- 5.6 — Pairwise calendar-year wins matrix -----------------------
    allocs = list(annual_pivot.columns)
    matrix = pd.DataFrame(0, index=allocs, columns=allocs)
    for year, row in annual_pivot.iterrows():
        for a in allocs:
            for b in allocs:
                if a == b:
                    continue
                if row[a] > row[b]:
                    matrix.loc[a, b] += 1
    n_years = len(annual_pivot)
    mat_head = (
        "<tr style='background:#f3f4f6;'><th>A beats B →</th>"
        + "".join(f"<th>{b}</th>" for b in allocs)
        + "</tr>"
    )
    mat_rows_html = ""
    for a in allocs:
        cells = [f"<td><b>{a}</b></td>"]
        for b in allocs:
            v = int(matrix.loc[a, b])
            if a == b:
                cells.append("<td style='background:#f3f4f6;'>—</td>")
            else:
                # colour by ratio
                ratio = v / n_years
                if ratio > 0.5:
                    bg = f"rgba(22,163,74,{0.3 + (ratio - 0.5) * 1.4:.2f})"
                else:
                    bg = f"rgba(220,38,38,{0.3 + (0.5 - ratio) * 1.4:.2f})"
                cells.append(
                    f"<td style='background:{bg};text-align:center;"
                    f"padding:5px 10px;'>{v}/{n_years}</td>"
                )
        mat_rows_html += "<tr>" + "".join(cells) + "</tr>"
    mat_html = (
        f"<h2>Pairwise calendar-year wins (rows = A, cols = B)</h2>"
        f"<table style='width:100%;border-collapse:collapse;font-size:0.9em;'>"
        f"<thead>{mat_head}</thead><tbody>{mat_rows_html}</tbody></table>"
        f"<p style='color:#555;font-size:0.85em;'>Cell A,B = how many years A "
        f"beat B (out of {n_years}). Green = A usually wins, red = A usually loses.</p>"
    )

    # --- 5.7 — Bear market analysis ------------------------------------
    spy_eq = next(r for r in results if r.name == "SPY_pure").daily_equity
    bears = _spy_bear_periods(spy_eq, threshold_pct=-15.0)
    bear_html = ""
    if bears:
        bear_rows = ""
        for b in bears:
            cells = [
                f"<td>{b['start'].date()} → {b['end'].date()}</td>",
                f"<td style='text-align:right;font-weight:600;'>{b['spy_max_dd']:+.1f}%</td>",
            ]
            for r in results:
                if r.name == "SPY_pure":
                    cells.append("<td style='text-align:right;color:#6b7280;'>—</td>")
                    continue
                dd_other = _max_dd_in_window(r.daily_equity, b["start"], b["end"])
                saved = dd_other - b["spy_max_dd"]
                colour = "#16a34a" if saved > 0 else "#dc2626"
                cells.append(
                    f"<td style='text-align:right;color:{colour};font-weight:600;'>"
                    f"{dd_other:+.1f}% <span style='color:#6b7280;font-weight:400;'>"
                    f"({saved:+.1f} pp)</span></td>"
                )
        # build header dynamically
        bear_cols = ["Period", "SPY DD"] + [r.name for r in results if r.name != "SPY_pure"]
        bear_head = (
            "<tr style='background:#f3f4f6;'>"
            + "".join(f"<th>{c}</th>" for c in bear_cols)
            + "</tr>"
        )
        bear_rows = ""
        for b in bears:
            cells = [
                f"<td>{b['start'].date()} → {b['end'].date()}</td>",
                f"<td style='text-align:right;font-weight:600;'>{b['spy_max_dd']:+.1f}%</td>",
            ]
            for r in results:
                if r.name == "SPY_pure":
                    continue
                dd_other = _max_dd_in_window(r.daily_equity, b["start"], b["end"])
                saved = dd_other - b["spy_max_dd"]
                colour = "#16a34a" if saved > 0 else "#dc2626"
                cells.append(
                    f"<td style='text-align:right;color:{colour};font-weight:600;'>"
                    f"{dd_other:+.1f}% <span style='color:#6b7280;font-weight:400;'>"
                    f"({saved:+.1f} pp)</span></td>"
                )
            bear_rows += "<tr>" + "".join(cells) + "</tr>"
        bear_html = (
            f"<h2>Bear-market protection (SPY DD &lt; −15%)</h2>"
            f"<p>For each SPY drawdown period, how the other allocations behaved. "
            f"Green = better (less DD), red = worse, value in parentheses is "
            f"(other allocation DD) − (SPY DD).</p>"
            f"<table style='width:100%;border-collapse:collapse;font-size:0.9em;'>"
            f"<thead>{bear_head}</thead><tbody>{bear_rows}</tbody></table>"
        )

    # --- 5.8 — Bull market analysis ------------------------------------
    spy_annual = next(r for r in results if r.name == "SPY_pure").annual_returns
    bull_years = [
        int(row["year"]) for _, row in spy_annual.iterrows() if float(row["return_pct"]) > 20.0
    ]
    bull_html = ""
    if bull_years:
        bull_cols = ["Year", "SPY %"] + [r.name for r in results if r.name != "SPY_pure"]
        bull_head = (
            "<tr style='background:#f3f4f6;'>"
            + "".join(f"<th>{c}</th>" for c in bull_cols)
            + "</tr>"
        )
        bull_rows = ""
        for y in bull_years:
            spy_r = float(spy_annual[spy_annual["year"] == y]["return_pct"].iloc[0])
            cells = [
                f"<td>{y}</td>",
                f"<td style='text-align:right;font-weight:600;color:#16a34a;'>{spy_r:+.2f}%</td>",
            ]
            for r in results:
                if r.name == "SPY_pure":
                    continue
                ar = r.annual_returns
                row = ar[ar["year"] == y]
                if row.empty:
                    cells.append("<td>—</td>")
                    continue
                other_r = float(row["return_pct"].iloc[0])
                diff = other_r - spy_r
                colour = "#16a34a" if diff > 0 else "#dc2626"
                cells.append(
                    f"<td style='text-align:right;color:{colour};font-weight:600;'>"
                    f"{other_r:+.2f}% <span style='color:#6b7280;font-weight:400;'>"
                    f"({diff:+.2f} pp)</span></td>"
                )
            bull_rows += "<tr>" + "".join(cells) + "</tr>"
        bull_html = (
            f"<h2>Bull-year upside (SPY annual return &gt; +20%)</h2>"
            f"<p>How much upside each defensive allocation gives up in strong "
            f"bull years. Negative parenthetical = trailing SPY.</p>"
            f"<table style='width:100%;border-collapse:collapse;font-size:0.9em;'>"
            f"<thead>{bull_head}</thead><tbody>{bull_rows}</tbody></table>"
        )

    # --- 5.9 — Trade-off framing ---------------------------------------
    framing = []
    for r in results:
        bullets = []
        m = metrics[metrics["Allocation"] == r.name].iloc[0]
        # Identify what this allocation is best/worst at
        for col, fmt, name, higher in [
            ("CAGR_pct", "{:+.2f}%", "CAGR", True),
            ("MaxDD_pct", "{:+.2f}%", "Max DD", True),
            ("Sharpe", "{:.2f}", "Sharpe", True),
            ("AnnVol_pct", "{:.2f}%", "Ann Vol", False),
        ]:
            best = metrics[col].max() if higher else metrics[col].min()
            worst = metrics[col].min() if higher else metrics[col].max()
            v = float(m[col])
            if abs(v - best) < 1e-6:
                bullets.append(
                    f"<li style='color:#16a34a;'>+ best <b>{name}</b> ({fmt.format(v)})</li>"
                )
            elif abs(v - worst) < 1e-6:
                bullets.append(
                    f"<li style='color:#dc2626;'>− worst <b>{name}</b> ({fmt.format(v)})</li>"
                )
        # delta vs SPY in calendar year wins
        wins = wins_per_alloc[r.name]
        bullets.append(f"<li>Won {wins}/{n_years} calendar years</li>")
        framing.append(
            f"<div style='padding:14px;margin:8px 0;border:1px solid #e5e7eb;"
            f"border-radius:6px;'><b>{r.name}</b> — {r.weights} "
            f"<i>({r.rebalancing})</i><br>"
            f"<ul style='margin:8px 0;'>" + "".join(bullets) + "</ul></div>"
        )
    framing_html = (
        "<h2>Trade-off summary</h2>"
        + "".join(framing)
        + "<div style='background:#eff6ff;border-left:4px solid #2563eb;padding:14px 18px;"
        "border-radius:4px;margin-top:14px;font-size:0.95em;'>"
        "<b>Framing (no recommendation):</b><ul>"
        "<li>For maximum long-term growth, ignoring drawdown: SPY-style allocations "
        "with highest CAGR.</li>"
        "<li>For minimum drawdown above all else: the heaviest-defensive mix.</li>"
        "<li>For middle ground (less DD than SPY, more growth than full defensive): "
        "the barbell allocations.</li>"
        "<li>For broad diversification without trusting cap-weighting: "
        "equal-weight allocations.</li></ul>"
        "<p style='margin-top:8px;'>Decision is yours — these are <i>numbers under "
        "the 2012-2025 lens only</i>. Past does not guarantee the future.</p></div>"
    )

    # --- assemble ------------------------------------------------------
    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Equity Sleeve — 5 Passive Allocations Comparison</title>
<style>
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         max-width:1300px;margin:24px auto;padding:0 16px;color:#1f2937; }}
  h1, h2 {{ border-bottom:1px solid #e5e7eb;padding-bottom:6px;margin-top:32px; }}
  table {{ width:100%;border-collapse:collapse;font-size:0.95em;margin:10px 0; }}
  th, td {{ border:1px solid #e5e7eb;padding:5px 9px; }}
  th {{ background:#f9fafb;text-align:left; }}
  ul {{ padding-left:20px; }}
</style></head><body>

<h1>Equity Sleeve — 5 Passive Allocations Comparison</h1>
<p style='color:#6b7280;'>Generated {datetime.now():%Y-%m-%d %H:%M} •
Source: <code>scripts/compare_passive_allocations.py</code> •
Backtester: <code>core/backtest/passive_portfolio.py</code></p>

{headline_html}

{table_html}

<h2>Equity curves (overlay)</h2>
{eq_html}

<h2>Drawdown comparison</h2>
{dd_html}

{cy_html}

{mat_html}

{bear_html}

{bull_html}

{framing_html}

<hr>
<p style='color:#9ca3af;font-size:0.85em;margin-top:32px;'>
Window: {START} → {END}  •  Initial capital: €{INITIAL_CAPITAL:,.0f}  •
Rebalance slippage: 5 bps per leg.  •  ETF availability:
XLC since 2018-06-19, XLRE since 2015-10-08 — weights renormalised onto
the available symbols when not yet listed.
</p></body></html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default=str(_REPO_ROOT / "outputs" / "equity_comparison"))
    ap.add_argument("--initial-capital", type=float, default=INITIAL_CAPITAL)
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[PassivePortfolioResult] = []
    for name, desc, weights, rebal in ALLOCATIONS:
        print(f"running {name} ({desc})...")
        p = PassivePortfolio(name=name, weights=weights, rebalancing=rebal)
        r = p.run(args.start, args.end, initial_capital_eur=args.initial_capital)
        results.append(r)
        print(
            f"  CAGR {r.cagr * 100:+.2f}%   Sharpe {r.sharpe:.3f}   "
            f"MaxDD {r.max_drawdown * 100:.2f}%   Final €{r.final_equity_eur:,.0f}"
        )

    # CSV outputs
    metrics = pd.DataFrame([_metrics_row(r) for r in results])
    metrics.to_csv(out_dir / "metrics_table.csv", index=False)

    eq_curves = pd.concat({r.name: r.daily_equity for r in results}, axis=1)
    eq_curves.to_csv(out_dir / "equity_curves.csv")

    _annual_matrix(results).to_csv(out_dir / "annual_returns.csv")

    # Holdings (one file per allocation)
    for r in results:
        if not r.holdings_history.empty:
            r.holdings_history.to_csv(out_dir / f"holdings_{r.name}.csv")

    # Per-allocation notes
    notes_block = "\n".join(
        [
            f"== {r.name} ==\n"
            + "\n".join("- " + n for n in r.notes)
            + f"\nRenorm days: {r.renormalisation_days}\nTotal slippage: €{r.total_slippage_cost_eur:.2f}\n"
            for r in results
        ]
    )
    (out_dir / "notes.txt").write_text(notes_block, encoding="utf-8")

    # HTML
    html_path = render_html(results, out_dir / "comparison.html")
    print(f"\nHTML: {html_path}")
    print(f"CSV:  {out_dir / 'metrics_table.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
