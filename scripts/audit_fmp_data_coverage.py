"""Audit FMP price coverage for the Quality Stocks universe.

Reads the parquet tree under ``<data_storage>/prices/`` (NOT the FMP API) and
reports earliest/latest date, total bars and gaps per symbol. Output:

  outputs/validation/data_coverage_audit.html
  outputs/validation/data_coverage_audit.json

The HTML carries a coverage heatmap by year, a "completeness" histogram and a
final recommended date range for the Quality Stocks full-history validation.

Survivorship bias is flagged explicitly: this audit uses the CURRENT S&P 500
constituents (from `FMPProvider.get_index_constituents`) — names that left the
index before today are absent. The historical-sp500-constituent endpoint is
available on the Premium plan and is flagged as a future-work item.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

# --- bootstrap ---
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# ---

import pandas as pd

from core.data.providers.fmp_provider import FMPProvider
from core.data.storage import DataStorage, load_global_config

log = logging.getLogger("audit_fmp_coverage")


def audit_symbol(storage: DataStorage, symbol: str) -> dict:
    """One symbol's coverage stats. No API calls — reads parquet only."""
    df = storage.get_prices(symbol, None, None)
    if df.empty:
        return {
            "symbol": symbol,
            "n_bars": 0,
            "min_date": None,
            "max_date": None,
            "earliest_year": None,
            "latest_year": None,
            "gap_count": 0,
            "longest_gap_days": 0,
        }
    # storage.get_prices returns a DatetimeIndex-indexed frame, not a "date" column
    if "date" in df.columns:
        dates = pd.to_datetime(df["date"]).sort_values().reset_index(drop=True)
    else:
        dates = pd.Series(pd.to_datetime(df.index)).sort_values().reset_index(drop=True)
    diffs = dates.diff().dt.days.fillna(0).astype(int)
    gap_count = int((diffs > 5).sum())  # >5 trading days suspicious
    longest_gap = int(diffs.max()) if len(diffs) > 0 else 0
    return {
        "symbol": symbol,
        "n_bars": int(len(df)),
        "min_date": dates.min().date().isoformat(),
        "max_date": dates.max().date().isoformat(),
        "earliest_year": int(dates.min().year),
        "latest_year": int(dates.max().year),
        "gap_count": gap_count,
        "longest_gap_days": longest_gap,
    }


def build_yearly_heatmap(per_symbol: list[dict]) -> pd.DataFrame:
    """rows = symbol, cols = year, value = 1 if any bar that year."""
    rows = []
    for r in per_symbol:
        if r["earliest_year"] is None:
            continue
        for y in range(r["earliest_year"], r["latest_year"] + 1):
            rows.append({"symbol": r["symbol"], "year": y, "covered": 1})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df.pivot_table(index="symbol", columns="year", values="covered", fill_value=0)


def recommend_window(
    per_symbol: list[dict], threshold_pct: float = 0.50
) -> tuple[date, date, dict]:
    """Pick the earliest year for which >= threshold_pct of symbols are already covered."""
    df = pd.DataFrame(per_symbol)
    if df.empty or df["earliest_year"].isna().all():
        return date(2016, 1, 1), date.today(), {"reason": "no data on disk", "covered_pct": 0.0}
    earliest_years = df["earliest_year"].dropna().astype(int)
    latest_years = df["latest_year"].dropna().astype(int)
    total = len(earliest_years)
    by_year = {y: int((earliest_years <= y).sum()) for y in range(2005, 2026)}
    rec_year = None
    for y in sorted(by_year):
        if by_year[y] / total >= threshold_pct:
            rec_year = y
            break
    if rec_year is None:
        rec_year = int(earliest_years.min())
    rec_end_year = int(latest_years.max())
    pct = by_year.get(rec_year, 0) / total if total else 0.0
    return (
        date(rec_year, 1, 1),
        date(rec_end_year, 12, 31),
        {"covered_pct": round(pct * 100, 1), "n_symbols": total, "by_year_count": by_year},
    )


def build_html(audit: dict, out_path: Path) -> Path:
    """Single-file HTML report."""
    import plotly.express as px

    per = audit["per_symbol"]
    heatmap = audit["heatmap_df"]
    rec_start = audit["recommended_window"]["start"]
    rec_end = audit["recommended_window"]["end"]
    rec_meta = audit["recommended_window"]["meta"]

    # Yearly count chart
    by_year = pd.DataFrame(
        [
            {"year": y, "symbols_with_data": rec_meta["by_year_count"][y]}
            for y in sorted(rec_meta["by_year_count"])
        ]
    )
    fig_y = px.bar(
        by_year,
        x="year",
        y="symbols_with_data",
        title="N° symbols with price history starting ≤ year",
        template="plotly_white",
    )
    fig_y.update_layout(height=300, margin=dict(l=0, r=0, t=40, b=0))

    fig_hm_html = ""
    if not heatmap.empty:
        # Resample heatmap to a coarser order: sort symbols by earliest_year
        order = pd.DataFrame(per).sort_values(["earliest_year", "symbol"])["symbol"].tolist()
        order = [s for s in order if s in heatmap.index]
        hm = heatmap.loc[order]
        fig_hm = px.imshow(
            hm.values,
            x=[str(c) for c in hm.columns],
            y=list(hm.index),
            color_continuous_scale=[[0, "#fee2e2"], [1, "#16a34a"]],
            aspect="auto",
            labels=dict(color="covered"),
        )
        fig_hm.update_layout(
            template="plotly_white",
            height=max(420, min(12 * len(hm), 1400)),
            title=f"Coverage heatmap — {len(hm)} symbols × years",
            xaxis=dict(side="top"),
            yaxis=dict(autorange="reversed"),
            margin=dict(l=60, r=10, t=60, b=20),
        )
        fig_hm_html = fig_hm.to_html(include_plotlyjs=False, full_html=False, div_id="heatmap")

    # Summary stats
    df = pd.DataFrame(per)
    df_with = df[df["n_bars"] > 0]
    summary_html = f"""
      <ul>
        <li><b>{audit["n_symbols_audited"]}</b> symbols audited
            (from FMP S&P 500 current constituents + SPY + IEF + indices)</li>
        <li><b>{audit["n_symbols_with_data"]}</b> have price data on disk</li>
        <li>Earliest date in cache: <b>{audit["min_date_overall"]}</b></li>
        <li>Latest date in cache: <b>{audit["max_date_overall"]}</b></li>
        <li>Median start year: <b>{int(df_with["earliest_year"].median())}</b>
            • 25th percentile: <b>{int(df_with["earliest_year"].quantile(0.25))}</b>
            • 75th percentile: <b>{int(df_with["earliest_year"].quantile(0.75))}</b></li>
        <li>Symbols with gaps &gt; 5 trading days: <b>{int((df_with["gap_count"] > 0).sum())}</b></li>
      </ul>
    """

    rec_html = f"""
    <div style='background:#f0f9ff;border-left:4px solid #2563eb;padding:12px 16px;
                margin:20px 0;border-radius:4px;'>
      <strong>Recommended validation window:</strong>
      <code>{rec_start.isoformat()}</code> → <code>{rec_end.isoformat()}</code>
      <br>{rec_meta.get("covered_pct", 0):.1f}% of the {rec_meta["n_symbols"]} audited
      symbols already have price history starting on or before
      <code>{rec_start.isoformat()}</code>.
    </div>
    """

    biases_html = """
    <div style='background:#fef3c7;border-left:4px solid #f59e0b;padding:12px 16px;
                margin:20px 0;border-radius:4px;'>
      <strong>⚠️ Survivorship bias:</strong>
      The current cache uses <em>current</em> S&P 500 constituents
      (<code>FMPProvider.get_index_constituents("sp500")</code>). Names that left
      the index before today are absent. The
      <code>/stable/historical-sp500-constituent</code> endpoint <em>is</em>
      available on the FMP Premium plan (verified, 1,500+ add/remove events
      back to 1992) and should be wired in for a fully unbiased validation —
      flagged as a Phase&nbsp;4 item.
    </div>
    """

    failing = sorted(df[df["n_bars"] == 0]["symbol"].tolist())[:30]
    incomplete = sorted(df_with[df_with["earliest_year"] > rec_start.year]["symbol"].tolist())[:30]

    failing_block = ""
    if failing:
        failing_block = (
            "<details><summary><b>Symbols with NO data on disk "
            f"({len(df) - len(df_with)} total)</b></summary>"
            f"<pre>{', '.join(failing)}{'…' if len(failing) >= 30 else ''}</pre></details>"
        )
    inc_block = (
        "<details><summary><b>Symbols whose history starts AFTER "
        f"{rec_start.year} ({(df_with['earliest_year'] > rec_start.year).sum()} total)"
        "</b></summary>"
        f"<pre>{', '.join(incomplete)}{'…' if len(incomplete) >= 30 else ''}</pre>"
        "<p style='color:#555;'>These are typically IPOs after the start "
        "date. They join the panel mid-window; the engine simply doesn't trade "
        "them before they exist.</p></details>"
    )

    yearly_html = fig_y.to_html(include_plotlyjs="cdn", full_html=False, div_id="yearly")

    page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>FMP Data Coverage Audit</title>
<style>
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         max-width:1200px;margin:24px auto;padding:0 16px;color:#1f2937; }}
  h1,h2 {{ border-bottom:1px solid #e5e7eb;padding-bottom:6px; }}
  code {{ background:#f3f4f6;padding:1px 4px;border-radius:3px; }}
  details {{ margin:8px 0; }}
  pre {{ white-space:pre-wrap;background:#f9fafb;padding:8px;border-radius:4px;
         font-size:0.85em; }}
</style></head><body>
<h1>FMP Data Coverage Audit</h1>
<p style='color:#6b7280;'>Generated {datetime.now():%Y-%m-%d %H:%M}</p>
{rec_html}
{biases_html}
<h2>Summary</h2>{summary_html}
<h2>By start year</h2>{yearly_html}
<h2>Heatmap</h2>{fig_hm_html}
<h2>Coverage gaps</h2>{failing_block}{inc_block}
</body></html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-html", default=None)
    ap.add_argument("--out-json", default=None)
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    cfg = load_global_config()
    storage = DataStorage.from_config(cfg)
    fmp = FMPProvider()

    log.info("loading current S&P 500 universe…")
    sp500 = fmp.get_index_constituents("sp500")
    extras = ["SPY", "IEF", "^GSPC", "^VIX"]
    universe = sorted(set(sp500) | set(extras))

    log.info("auditing %d symbols (parquet only, no API calls)", len(universe))
    per_symbol = [audit_symbol(storage, s) for s in universe]

    df = pd.DataFrame(per_symbol)
    df_with = df[df["n_bars"] > 0]
    min_d = df_with["min_date"].min() if not df_with.empty else None
    max_d = df_with["max_date"].max() if not df_with.empty else None

    rec_start, rec_end, rec_meta = recommend_window(per_symbol, threshold_pct=0.50)

    audit = {
        "generated_at": datetime.utcnow().isoformat(),
        "n_symbols_audited": len(per_symbol),
        "n_symbols_with_data": int((df["n_bars"] > 0).sum()),
        "min_date_overall": min_d,
        "max_date_overall": max_d,
        "recommended_window": {
            "start": rec_start,
            "end": rec_end,
            "meta": rec_meta,
        },
        "per_symbol": per_symbol,
        "heatmap_df": build_yearly_heatmap(per_symbol),
    }

    out_html = (
        Path(args.out_html)
        if args.out_html
        else (_REPO_ROOT / "outputs" / "validation" / "data_coverage_audit.html")
    )
    out_json = (
        Path(args.out_json)
        if args.out_json
        else (_REPO_ROOT / "outputs" / "validation" / "data_coverage_audit.json")
    )
    out_html.parent.mkdir(parents=True, exist_ok=True)

    # Build HTML (this imports plotly)
    html_path = build_html(audit, out_html)

    # Drop the heatmap DataFrame for JSON serialisation
    serial = {k: v for k, v in audit.items() if k != "heatmap_df"}
    serial["recommended_window"]["start"] = serial["recommended_window"]["start"].isoformat()
    serial["recommended_window"]["end"] = serial["recommended_window"]["end"].isoformat()
    out_json.write_text(json.dumps(serial, indent=2, default=str), encoding="utf-8")

    print(f"HTML report: {html_path}")
    print(f"JSON report: {out_json}")
    print(
        f"Recommended window: {rec_start} -> {rec_end} "
        f"({rec_meta.get('covered_pct', 0):.1f}% coverage at start)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
