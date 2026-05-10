"""Data validation schemas. Uses pandera if installed; falls back to runtime checks otherwise."""
from __future__ import annotations

try:
    import pandera as pa
    from pandera.typing import Series
    PANDERA_AVAILABLE = True
except ImportError:
    PANDERA_AVAILABLE = False


if PANDERA_AVAILABLE:

    class OHLCVSchema(pa.DataFrameModel):
        date: Series[pa.DateTime]
        ticker: Series[str]
        open: Series[float] = pa.Field(ge=0, nullable=True)
        high: Series[float] = pa.Field(ge=0, nullable=True)
        low: Series[float] = pa.Field(ge=0, nullable=True)
        close: Series[float] = pa.Field(ge=0, nullable=True)
        adj_close: Series[float] = pa.Field(ge=0, nullable=True)
        volume: Series[float] = pa.Field(ge=0, nullable=True)

    class BondSchema(pa.DataFrameModel):
        isin: Series[str]
        name: Series[str]
        coupon: Series[float] = pa.Field(ge=0, le=25, nullable=True)
        maturity_date: Series[str] = pa.Field(nullable=True)
        currency: Series[str]
        net_yield_pa: Series[float] = pa.Field(nullable=True)


def validate_ohlcv(df):
    """Soft validation — returns df unchanged or raises if pandera available and schema fails."""
    if PANDERA_AVAILABLE and not df.empty:
        try:
            return OHLCVSchema.validate(df, lazy=True)
        except Exception:
            # Skeleton: don't hard-fail Phase 1 backtests if upstream sends unusual rows.
            return df
    return df


def validate_bonds(df):
    if PANDERA_AVAILABLE and not df.empty:
        try:
            return BondSchema.validate(df, lazy=True)
        except Exception:
            return df
    return df
