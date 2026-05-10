"""Performance metrics, attribution, correlation analytics."""

from quant_lab.core.analytics.metrics import (
    compute_metrics, sharpe, sortino, calmar, max_drawdown,
    cagr, annualised_vol, trade_stats, underwater,
)

__all__ = [
    "compute_metrics", "sharpe", "sortino", "calmar", "max_drawdown",
    "cagr", "annualised_vol", "trade_stats", "underwater",
]
