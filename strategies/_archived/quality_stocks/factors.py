"""Quality + momentum factor calculations for Quality Stocks.

Point-in-time discipline (CRITICAL):
  - When computing a quality score AS OF date D, we only use fundamentals
    whose filing_date <= D. Using fiscal `period_end_date` would create
    look-ahead bias (a 2023-09 earnings report is filed in late October).
  - The FMP cache stores filing_date and falls back to period_end + 90d
    when filingDate is absent. This 90d lag approximates the standard
    SEC/IFRS filing window.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# Field names in FMP key-metrics & ratios — exact match needed.
F_ROIC = "returnOnInvestedCapital"
F_FCF_YIELD = "freeCashFlowYield"
F_FCF_TO_EQUITY = "freeCashFlowToEquity"
F_DEBT_EQUITY = "debtToEquityRatio"


# ---- single-symbol metric extraction -------------------------------------

def _latest_at(df: pd.DataFrame, date: pd.Timestamp) -> Optional[pd.Series]:
    """Latest fundamentals row whose filing_date <= date. None if empty."""
    if df is None or df.empty or "filing_date" not in df.columns:
        return None
    cutoff = pd.to_datetime(date)
    visible = df[df["filing_date"] <= cutoff]
    if visible.empty:
        return None
    return visible.sort_values("filing_date", ascending=False).iloc[0]


def _roic_series_at(km_df: pd.DataFrame, date: pd.Timestamp, last_n: int = 5) -> np.ndarray:
    """Return the last N annual ROIC values visible at `date` (filing_date <= date)."""
    if km_df is None or km_df.empty:
        return np.array([])
    cutoff = pd.to_datetime(date)
    visible = km_df[km_df["filing_date"] <= cutoff]
    if visible.empty or F_ROIC not in visible.columns:
        return np.array([])
    vals = visible.sort_values("filing_date", ascending=False)[F_ROIC].head(last_n).to_numpy()
    return vals[np.isfinite(vals)]


def extract_quality_factors(
    symbol: str,
    date: pd.Timestamp,
    key_metrics: pd.DataFrame,
    ratios: pd.DataFrame,
) -> dict:
    """Return {factor_name: value} or empty dict if insufficient data."""
    km_row = _latest_at(key_metrics, date)
    rt_row = _latest_at(ratios, date)
    if km_row is None or rt_row is None:
        return {}

    roic = km_row.get(F_ROIC, np.nan)
    fcf_yield = km_row.get(F_FCF_YIELD, np.nan)
    fcf_to_eq = km_row.get(F_FCF_TO_EQUITY, np.nan)
    debt_eq = rt_row.get(F_DEBT_EQUITY, np.nan)

    # Stability: mean(ROIC_5y) / std(ROIC_5y). Higher = more stable.
    roic_history = _roic_series_at(key_metrics, date, last_n=5)
    if len(roic_history) >= 3 and np.nanstd(roic_history, ddof=1) > 0:
        stable_roic = float(np.nanmean(roic_history) / np.nanstd(roic_history, ddof=1))
    else:
        stable_roic = np.nan

    # 1/debt_equity: low leverage = high score
    inv_debt_eq = float(1.0 / debt_eq) if (pd.notna(debt_eq) and debt_eq > 0) else np.nan

    return {
        "roic": float(roic) if pd.notna(roic) else np.nan,
        "fcf_yield": float(fcf_yield) if pd.notna(fcf_yield) else np.nan,
        "cash_return": float(fcf_to_eq) if pd.notna(fcf_to_eq) else np.nan,
        "inv_debt_eq": inv_debt_eq,
        "stable_roic": stable_roic,
    }


# ---- cross-sectional ranking ---------------------------------------------

def calculate_quality_score(
    factor_table: pd.DataFrame,
    weights: Optional[dict[str, float]] = None,
) -> pd.Series:
    """Composite quality score.

    factor_table: rows = symbols, cols = factor names (roic, fcf_yield, ...).
    Each column is percentile-ranked across symbols (NaN -> excluded from
    that column's rank); the score is the sum of weighted ranks.
    """
    if factor_table.empty:
        return pd.Series(dtype=float)
    if weights is None:
        weights = {"roic": 1.0, "fcf_yield": 1.0, "cash_return": 1.0,
                   "inv_debt_eq": 1.0, "stable_roic": 1.0}
    score = pd.Series(0.0, index=factor_table.index)
    contrib_count = pd.Series(0.0, index=factor_table.index)
    for col, w in weights.items():
        if col not in factor_table.columns:
            continue
        col_series = factor_table[col]
        ranks = col_series.rank(pct=True)  # NaN stays NaN
        contrib = ranks.fillna(0) * w
        score = score.add(contrib, fill_value=0)
        contrib_count = contrib_count + (ranks.notna().astype(float) * w)
    # Normalise by total weight actually used (so symbols with mostly-NaN
    # factors don't get penalised twice). Symbols with zero coverage -> NaN.
    out = score / contrib_count.replace(0, np.nan)
    return out.sort_values(ascending=False)


# ---- momentum -----------------------------------------------------------

def calculate_momentum(
    panel: pd.DataFrame,
    symbols: Iterable[str],
    date: pd.Timestamp,
    *,
    lookback_days: int = 126,
    skip_days: int = 10,
) -> pd.Series:
    """Log return over (lookback - skip) days, skipping the last `skip_days`.

    panel: wide DataFrame indexed by date, columned by symbol (adj_close).
    """
    if panel is None or panel.empty:
        return pd.Series(dtype=float)
    end_idx = panel.index <= pd.to_datetime(date)
    if not end_idx.any():
        return pd.Series(dtype=float)
    sub = panel.loc[end_idx]
    if len(sub) < lookback_days + 1:
        return pd.Series(dtype=float)
    # `t` = today index; `start` = lookback bars ago; `skip_end` = skip_days back from t
    t_idx = len(sub) - 1
    start_idx = t_idx - lookback_days
    skip_end_idx = t_idx - skip_days
    if start_idx < 0 or skip_end_idx <= start_idx:
        return pd.Series(dtype=float)

    p_start = sub.iloc[start_idx]
    p_end = sub.iloc[skip_end_idx]
    avail = [s for s in symbols if s in sub.columns]
    out = {}
    for s in avail:
        ps, pe = p_start.get(s), p_end.get(s)
        if pd.notna(ps) and pd.notna(pe) and ps > 0 and pe > 0:
            out[s] = float(np.log(pe / ps))
    return pd.Series(out, name="momentum").sort_values(ascending=False)
