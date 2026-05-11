"""Deprecated — moved to ``portfolio._legacy.aggregator``.

Phase 3 replaced the dynamic multi-strategy aggregator with a static
sleeve-based portfolio (``portfolio.static_allocator`` + ``portfolio.state``).
This module is kept as a thin re-export for back-compat.
"""

from __future__ import annotations

import warnings

from portfolio._legacy.aggregator import (  # noqa: F401
    PortfolioAggregator,
    PortfolioResult,
    StrategyRunResult,
    combined_equity,
    load_strategy_outputs,
)

warnings.warn(
    "portfolio.aggregator is deprecated; new sleeve model lives in "
    "portfolio.static_allocator + portfolio.state",
    DeprecationWarning,
    stacklevel=2,
)
