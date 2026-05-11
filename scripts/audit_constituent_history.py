"""Audit FMP historical-constituent membership coverage for the S&P 500.

Reads the ``index_membership_history`` DuckDB table (populated by
``FMPProvider.get_historical_index_constituents``) and emits a coverage
report:

  outputs/validation/constituent_history_audit.html
  outputs/validation/constituent_history_audit.json

Key questions answered:
  - How many membership change events do we have, and over what window?
  - Distribution by year, by reason (M&A, market-cap, IPO, bankruptcy).
  - "Deceased" tickers: in the history but no longer in the current set.
    Of these, how many fall inside our backtest window (≥ 2009)?
  - For backtests using survivorship-aware universe, what fraction of the
    historical universe is *missing* from the price cache at each date?
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

import pandas as pd
import plotly.express as px

from core.data.providers.fmp_provider import FMPProvider
from core.data.storage import DataStorage, load_global_config


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-html", default=None)
    ap.add_argument("--out-json", default=None)
    args = ap.parse_args(argv)

    fmp = FMPProvider()
    storage = DataStorage.from_config(load_global_config())

    print("Fetching historical S&P 500 membership events...")
    events = fmp.get_historical_index_constituents("sp500")
    current = set(fmp.get_index_constituents("sp500"))

    if events.empty:
        raise RuntimeError("no membership history available — endpoint failure?")

    n_events = len(events)
    min_date = events["effective_date"].min().date()
    max_date = events["effective_date"].max().date()

    events["year"] = events["effective_date"].dt.year

    # Tickers ever in SP500
    ever = set(events["symbol"].unique())
    deceased_all = ever - current

    # Recent (2009+) — relevant to backtest window
    recent_events = events[events["effective_date"] >= "2009-01-01"]
    recent_ever = set(recent_events["symbol"].unique())
    recent_deceased = recent_ever - current

    # Which deceased tickers have a parquet file?
    parquet_syms = set(storage.get_universe_symbols("us/sp500"))
    deceased_with_data = recent_deceased & parquet_syms
    deceased_no_data = recent_deceased - parquet_syms

    # Top reasons (filter blanks)
    reasons = (
        events["reason"]
        .fillna("")
        .replace("", pd.NA)
        .dropna()
        .str.slice(0, 60)
        .value_counts()
        .head(15)
    )

    # By-year chart
    by_year = events.groupby(["year", "action"]).size().unstack(fill_value=0).reset_index()
    fig_y = px.bar(
        by_year,
        x="year",
        y=[c for c in by_year.columns if c != "year"],
        title="Membership change events per year (added vs removed)",
        template="plotly_white",
        barmode="stack",
    )
    fig_y.update_layout(height=300, margin=dict(l=0, r=0, t=40, b=0), legend_title=None)

    # Universe size at sample dates — how much does it shrink the trading universe?
    sample_dates = [
        "2009-01-01",
        "2012-01-01",
        "2015-01-01",
        "2018-01-01",
        "2021-01-01",
        "2024-01-01",
    ]
    sample_rows = []
    for ds in sample_dates:
        u = fmp.get_constituents_at_date("sp500", as_of=pd.Timestamp(ds))
        u_in_cache = [s for s in u if s in parquet_syms]
        sample_rows.append(
            {
                "date": ds,
                "universe_size": len(u),
                "in_price_cache": len(u_in_cache),
                "missing_from_cache": len(u) - len(u_in_cache),
                "coverage_pct": round(len(u_in_cache) / len(u) * 100, 1) if u else 0.0,
            }
        )
    sample_df = pd.DataFrame(sample_rows)

    audit = {
        "generated_at": datetime.utcnow().isoformat(),
        "n_events_total": int(n_events),
        "event_date_range": [str(min_date), str(max_date)],
        "n_tickers_ever": int(len(ever)),
        "n_tickers_current": int(len(current)),
        "n_deceased_total": int(len(deceased_all)),
        "n_recent_deceased_since_2009": int(len(recent_deceased)),
        "n_deceased_with_price_data": int(len(deceased_with_data)),
        "n_deceased_no_price_data": int(len(deceased_no_data)),
        "universe_size_at_sample_dates": sample_rows,
        "top_reasons": [{"reason": r, "count": int(n)} for r, n in reasons.to_dict().items()],
    }

    out_json = (
        Path(args.out_json)
        if args.out_json
        else (_REPO_ROOT / "outputs" / "validation" / "constituent_history_audit.json")
    )
    out_html = (
        Path(args.out_html)
        if args.out_html
        else (_REPO_ROOT / "outputs" / "validation" / "constituent_history_audit.html")
    )
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")

    # --- HTML --------------------------------------------------------------

    yearly_html = fig_y.to_html(include_plotlyjs="cdn", full_html=False)
    sample_html = sample_df.to_html(index=False)
    reasons_html = pd.DataFrame(audit["top_reasons"]).to_html(index=False)

    deceased_sample_list = sorted(deceased_no_data)[:40]
    deceased_block = (
        "<details><summary><b>Deceased tickers (in history since 2009, "
        f"no longer in current index, no price data on disk: {len(deceased_no_data)})</b></summary>"
        f"<pre>{', '.join(deceased_sample_list)}{'…' if len(deceased_no_data) > 40 else ''}</pre>"
        "</details>"
    )

    # Survivorship correction effectiveness banner
    avg_cov = sample_df["coverage_pct"].mean()
    if avg_cov < 80:
        eff_class = "fef3c7"
        eff_text = (
            f"⚠️ <b>Partial coverage</b>: avg {avg_cov:.0f}% of the historical "
            "universe has price data in the local cache. The remaining ~"
            f"{100 - avg_cov:.0f}% are delisted tickers we have no prices for, "
            "so the survivorship correction is partial (lookahead bias removed, "
            "but losers' returns are still missing). Documented in the report."
        )
    else:
        eff_class = "dcfce7"
        eff_text = (
            f"✅ <b>Strong coverage</b>: avg {avg_cov:.0f}% of the historical "
            "universe has price data on disk. Survivorship correction is "
            "effectively complete."
        )

    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>FMP S&P 500 Membership Coverage Audit</title>
<style>
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         max-width:1200px;margin:24px auto;padding:0 16px;color:#1f2937; }}
  h1,h2 {{ border-bottom:1px solid #e5e7eb;padding-bottom:6px; }}
  code {{ background:#f3f4f6;padding:1px 4px;border-radius:3px; }}
  pre {{ white-space:pre-wrap;background:#f9fafb;padding:8px;border-radius:4px;
         font-size:0.85em; }}
  table {{ width:100%;border-collapse:collapse;font-size:0.9em; }}
  th,td {{ border:1px solid #e5e7eb;padding:5px 9px;text-align:left; }}
  th {{ background:#f9fafb; }}
  .summary {{ background:#{eff_class};border-left:4px solid #f59e0b;
               padding:12px 16px;margin:16px 0;border-radius:4px; }}
</style></head><body>
<h1>FMP S&amp;P 500 Membership History — Audit</h1>
<p style='color:#6b7280;'>Generated {datetime.now():%Y-%m-%d %H:%M}</p>

<div class="summary">{eff_text}</div>

<h2>Summary</h2>
<ul>
  <li>Membership change events: <b>{n_events:,}</b></li>
  <li>Event date range: <b>{min_date}</b> &rarr; <b>{max_date}</b></li>
  <li>Unique tickers ever in S&amp;P 500: <b>{len(ever):,}</b></li>
  <li>Current constituents: <b>{len(current):,}</b></li>
  <li>"Deceased" (ever in S&amp;P but not today): <b>{len(deceased_all):,}</b></li>
  <li>"Deceased since 2009" (inside backtest window): <b>{len(recent_deceased):,}</b></li>
  <li>Deceased with price data on disk: <b>{len(deceased_with_data):,}</b> (= survivorship-correctable)</li>
  <li>Deceased without price data: <b>{len(deceased_no_data):,}</b> (= the partial-coverage gap)</li>
</ul>

<h2>Universe size at sample dates</h2>
{sample_html}

<h2>Events per year</h2>
{yearly_html}

<h2>Top reasons</h2>
{reasons_html}

<h2>Deceased ticker sample</h2>
{deceased_block}

</body></html>"""
    out_html.write_text(page, encoding="utf-8")

    print(f"\nHTML report: {out_html}")
    print(f"JSON report: {out_json}")
    print(
        f"Events: {n_events}  Deceased (post-2009): {len(recent_deceased)} "
        f"(in cache: {len(deceased_with_data)}, missing: {len(deceased_no_data)})"
    )
    print(f"Avg historical-universe price coverage at sample dates: {avg_cov:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
