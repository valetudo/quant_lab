"""Bond Ladder positions — parquet persistence with per-modification backup.

Schema (one row per position, both active and historical):

    isin                  str    ISIN code, unique within ``status == 'active'``
    description           str    free-text label (BondsScreener "name")
    quantity              int    face value units, typically 1000 EUR each
    avg_purchase_price    float  as % of face (100 = par)
    purchase_date         date   when the position was opened
    ytm_at_purchase       float  net YTM at purchase, % (informational)
    ytm_current           float  latest YTM snapshot
    current_price         float  latest price, % of face
    current_market_value_eur float  computed (quantity × current_price / 100)
    coupon                float  annual coupon, % of face
    maturity_date         date   bond maturity
    years_to_maturity     float  snapshot at last refresh
    nation                str    sovereign nation or issuer nation
    issuer_type           str    'Government' | 'Corporate'
    rating                str    optional (corporate only)
    sector                str    optional (corporate only)
    status                str    'active' | 'matured' | 'sold'
    closed_date           date   when status changed to matured/sold (nullable)
    closed_price          float  closing price (nullable)
    notes                 str    free-text

The file lives at ``data_storage/bonds/positions.parquet``. Every write is
preceded by a copy to ``positions_backup_<UTC-isoformat>.parquet`` so a fat-
finger entry can always be rolled back manually.
"""

from __future__ import annotations

import logging
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)

POSITION_COLUMNS = [
    "isin",
    "description",
    "quantity",
    "avg_purchase_price",
    "purchase_date",
    "ytm_at_purchase",
    "ytm_current",
    "current_price",
    "current_market_value_eur",
    "coupon",
    "maturity_date",
    "years_to_maturity",
    "nation",
    "issuer_type",
    "rating",
    "sector",
    "status",
    "closed_date",
    "closed_price",
    "notes",
]


def _default_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data_storage" / "bonds" / "positions.parquet"


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=POSITION_COLUMNS)


def load_positions(path: Optional[str | Path] = None) -> pd.DataFrame:
    """Load the positions parquet. Returns an empty DataFrame if none exists."""
    p = Path(path) if path else _default_path()
    if not p.exists():
        return _empty_df()
    try:
        df = pd.read_parquet(p)
    except Exception as e:
        log.warning("could not read positions parquet (%s) — returning empty", e)
        return _empty_df()
    # Add any missing columns so callers can rely on the schema.
    for c in POSITION_COLUMNS:
        if c not in df.columns:
            df[c] = pd.NA
    return df[POSITION_COLUMNS]


def save_positions(df: pd.DataFrame, path: Optional[str | Path] = None) -> Path:
    """Write the positions parquet atomically, backing up any prior version."""
    p = Path(path) if path else _default_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        backup = p.with_name(f"positions_backup_{ts}.parquet")
        try:
            shutil.copy2(p, backup)
        except Exception as e:
            log.warning("backup of %s failed: %s", p, e)
    # Ensure all expected columns exist.
    for c in POSITION_COLUMNS:
        if c not in df.columns:
            df[c] = pd.NA
    df = df[POSITION_COLUMNS].copy()
    tmp = p.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(p)
    return p


def add_position(
    *,
    isin: str,
    description: str,
    quantity: int,
    avg_purchase_price: float,
    purchase_date: date,
    coupon: float,
    maturity_date: date,
    ytm_at_purchase: float,
    nation: Optional[str] = None,
    issuer_type: Optional[str] = None,
    rating: Optional[str] = None,
    sector: Optional[str] = None,
    notes: Optional[str] = "",
    current_price: Optional[float] = None,
    path: Optional[str | Path] = None,
) -> pd.DataFrame:
    """Append a position to the ladder. ``isin`` must not be already active."""
    df = load_positions(path)
    active_isins = set(df[df["status"] == "active"]["isin"].tolist())
    if isin in active_isins:
        raise ValueError(
            f"ISIN {isin!r} is already an active position. "
            f"Use update_position() to change quantity or price, "
            f"or close the existing position first."
        )
    today = date.today()
    pdate = (
        purchase_date if isinstance(purchase_date, date) else date.fromisoformat(str(purchase_date))
    )
    mdate = (
        maturity_date if isinstance(maturity_date, date) else date.fromisoformat(str(maturity_date))
    )
    years = max(0.0, (mdate - today).days / 365.25)
    px = float(current_price) if current_price is not None else float(avg_purchase_price)
    row = {
        "isin": isin,
        "description": description,
        "quantity": int(quantity),
        "avg_purchase_price": float(avg_purchase_price),
        "purchase_date": pdate,
        "ytm_at_purchase": float(ytm_at_purchase),
        "ytm_current": float(ytm_at_purchase),
        "current_price": px,
        "current_market_value_eur": float(quantity) * px / 100.0,
        "coupon": float(coupon),
        "maturity_date": mdate,
        "years_to_maturity": years,
        "nation": nation,
        "issuer_type": issuer_type,
        "rating": rating,
        "sector": sector,
        "status": "active",
        "closed_date": None,
        "closed_price": None,
        "notes": notes or "",
    }
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    save_positions(df, path)
    # Dual-write: mirror into the unified PositionTracker so cross-asset
    # pages (Portfolio Overview, Home, Aggiorna Posizioni) see this bond.
    try:
        from portfolio.position_tracker import PositionTracker

        PositionTracker().add_bond(
            isin=isin,
            name=description or isin,
            quantity=float(quantity),
            avg_purchase_price=float(avg_purchase_price),
            purchase_date=pdate,
            issuer=(nation if (issuer_type or "").lower() == "government" else None),
            maturity_date=mdate,
            coupon_rate=float(coupon) / 100.0 if coupon else None,
            coupon_frequency=1,
            ytm_at_purchase=float(ytm_at_purchase) / 100.0 if ytm_at_purchase else None,
            rating=rating,
            notes=notes or "",
        )
    except Exception as e:
        log.warning("dual-write to PositionTracker failed for %s: %s", isin, e)
    return df


def update_position(
    isin: str,
    *,
    quantity: Optional[int] = None,
    avg_purchase_price: Optional[float] = None,
    current_price: Optional[float] = None,
    ytm_current: Optional[float] = None,
    notes: Optional[str] = None,
    path: Optional[str | Path] = None,
) -> pd.DataFrame:
    df = load_positions(path)
    mask = (df["isin"] == isin) & (df["status"] == "active")
    if not mask.any():
        raise KeyError(f"no active position with ISIN {isin}")
    idx = df[mask].index[0]
    if quantity is not None:
        df.at[idx, "quantity"] = int(quantity)
    if avg_purchase_price is not None:
        df.at[idx, "avg_purchase_price"] = float(avg_purchase_price)
    if current_price is not None:
        df.at[idx, "current_price"] = float(current_price)
        df.at[idx, "current_market_value_eur"] = (
            float(df.at[idx, "quantity"]) * float(current_price) / 100.0
        )
    if ytm_current is not None:
        df.at[idx, "ytm_current"] = float(ytm_current)
    if notes is not None:
        df.at[idx, "notes"] = notes
    save_positions(df, path)
    return df


def close_position(
    isin: str,
    *,
    reason: str = "matured",
    closed_price: Optional[float] = None,
    closed_date: Optional[date] = None,
    path: Optional[str | Path] = None,
) -> pd.DataFrame:
    """Mark a position matured or sold. ``reason`` must be 'matured' or 'sold'."""
    if reason not in ("matured", "sold"):
        raise ValueError(f"reason must be 'matured' or 'sold', got {reason!r}")
    df = load_positions(path)
    mask = (df["isin"] == isin) & (df["status"] == "active")
    if not mask.any():
        raise KeyError(f"no active position with ISIN {isin}")
    idx = df[mask].index[0]
    df.at[idx, "status"] = reason
    df.at[idx, "closed_date"] = closed_date or date.today()
    if closed_price is not None:
        df.at[idx, "closed_price"] = float(closed_price)
    save_positions(df, path)
    return df
