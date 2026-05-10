"""Cost models — linear bps + sqrt-volume Kyle impact.

Migrated and generalized from pair_trading_ITA._leg_cost. The interface
is per-leg (single instrument); the engine sums across legs of a signal.
"""
from __future__ import annotations
from typing import Optional


def leg_cost(
    notional_eur: float,
    *,
    commission_bps: float = 5.0,
    slippage_bps: float = 5.0,
    ticker: Optional[str] = None,
    slippage_model: str = "linear_bps",
    avg_daily_turnover_eur: Optional[dict] = None,
    sqrt_impact_kappa: float = 0.10,
) -> float:
    """Round-trip leg cost (commission + slippage) in EUR.

    `slippage_model`:
      - "linear_bps" : cost = notional × (commission + slippage)/1e4
      - "sqrt_volume": adds Kyle/Almgren extra component
                       notional × (slippage/1e4) × kappa × sqrt(notional/ADV)
                       when ADV is available for `ticker`.
    """
    notional = abs(float(notional_eur))
    base = notional * (commission_bps + slippage_bps) / 1e4
    if slippage_model == "sqrt_volume" and ticker and avg_daily_turnover_eur:
        adv = avg_daily_turnover_eur.get(ticker)
        if adv and adv > 0 and notional > 0:
            ratio = notional / adv
            extra = notional * (slippage_bps / 1e4) * sqrt_impact_kappa * (ratio ** 0.5)
            base += extra
    return float(base)
