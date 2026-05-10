"""Bond selection — rank, filter, and pick the top N by net yield.

Uses the enrichment helpers from `core.data.providers._bonds_impl.calculations`
(which contain the proven yield/duration/anomaly logic from the bonds project).
"""
from __future__ import annotations

from typing import Iterable

from quant_lab.core.data.providers._bonds_impl import calculations as _calc


def filter_bonds(
    bonds: Iterable[dict],
    *,
    sovereign_only: bool = True,
    currency: str = "EUR",
    min_yield_pct: float = 2.0,
    max_duration_years: float = 8.0,
    min_years_to_maturity: float = 0.75,
    exclude_callable: bool = True,
    exclude_inflation_linked: bool = True,
) -> list[dict]:
    """Apply filters used by the screener and by the strategy. Returns filtered list."""
    out = []
    want_ccy = (currency or "").upper()
    for b in bonds:
        if b.get("net_yield_pa") is None:
            continue
        if exclude_inflation_linked and b.get("inflation_linked"):
            continue
        if exclude_callable and b.get("is_callable"):
            continue
        if want_ccy and (b.get("currency") or "").upper() != want_ccy:
            continue
        years = b.get("years_to_maturity")
        if years is None or years < min_years_to_maturity or years > max_duration_years:
            continue
        if float(b["net_yield_pa"]) < min_yield_pct:
            continue
        if sovereign_only and (b.get("issuer_type") or "").lower() != "government":
            continue
        out.append(b)
    return out


def select_top_n(
    bonds: Iterable[dict],
    n: int = 20,
    *,
    sort_by: str = "net_yield_pa",
    descending: bool = True,
) -> list[dict]:
    """Sort bonds by `sort_by` then return the top N."""
    rows = list(bonds)
    rows.sort(key=lambda b: b.get(sort_by) or 0.0, reverse=descending)
    return rows[:max(0, int(n))]


def enrich_and_select(
    raw_bonds: Iterable[dict],
    *,
    n_bonds: int = 20,
    **filter_kwargs,
) -> list[dict]:
    """Enrich + filter + rank — the full screener pipeline in one call."""
    enriched = [_calc.enrich_bond(b) for b in raw_bonds]
    filtered = filter_bonds(enriched, **filter_kwargs)
    return select_top_n(filtered, n=n_bonds)
