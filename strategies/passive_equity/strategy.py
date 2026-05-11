"""PassiveEquity — buy-and-hold a single ETF (Phase 4 equity sleeve).

Replaces Quality Stocks V5 after V5 was archived for underperforming SPY
by −4.6 pp/yr over 13 years OOS (see ``_migration_log/V5_VS_SPY_DECISION.md``).

Logic:
  - On the first bar where the configured symbol has a price, allocate the
    full configured capital to it (1 leg, long).
  - Never sell. Never rebalance. Dividends are reinvested implicitly via
    ``adj_close`` from the price source.

This is technically a Strategy (subclasses ``core.strategy.Strategy``) so
the portfolio framework can track it uniformly with the active strategies,
but it generates exactly one signal in its lifetime.

Default symbol is ``CSPX.L`` (iShares Core S&P 500 UCITS ETF). For
backtesting on price tables that do not carry CSPX, ``SPY`` is a 99 %+
correlated US-listed proxy — wired as a fallback in
``DataStorage.get_prices_with_proxy``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from core.strategy.base import Strategy
from core.strategy.signals import Action, Position, Signal


def _load_config(path: Optional[Path]) -> dict:
    if path is None:
        path = Path(__file__).resolve().parent / "config.yaml"
    if not Path(path).exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class PassiveEquity(Strategy):
    """Buy-and-hold a single ETF, equal-capital, no rebalance."""

    def __init__(
        self,
        *,
        symbol: Optional[str] = None,
        initial_capital_eur: Optional[float] = None,
        config_path: Optional[Path] = None,
        strategy_id: str = "passive_equity",
    ) -> None:
        cfg = _load_config(config_path)
        self._strategy_id = strategy_id
        # Explicit kwargs win over config-file defaults
        self._symbol = symbol or cfg.get("symbol", "CSPX.L")
        self._initial_capital_eur = float(
            initial_capital_eur
            if initial_capital_eur is not None
            else cfg.get("capital_eur", 30_000.0)
        )
        # Internal state
        self._bought = False
        self._actual_symbol: Optional[str] = None  # may be a proxy

    @property
    def strategy_id(self) -> str:
        return self._strategy_id

    @property
    def universe(self) -> list[str]:
        return [self._symbol]

    def on_init(self, history: pd.DataFrame) -> None:
        self._bought = False
        self._actual_symbol = None

    def _resolve_symbol(self, history: pd.DataFrame) -> Optional[str]:
        """Find a tradeable column for the configured symbol.

        Tries the configured symbol first; if missing, tries any
        retail-proxy fallback. Returns the column name to trade, or
        ``None`` if neither is in the panel.
        """
        if self._symbol in history.columns:
            return self._symbol
        # Hard-coded retail proxies mirror DataStorage.RETAIL_PROXIES, kept
        # here so the strategy is independent of the storage helper.
        proxies = {
            "CSPX.L": "SPY",
            "CSPX.MI": "SPY",
            "VUAA.L": "SPY",
            "SPY5.L": "SPY",
        }
        fallback = proxies.get(self._symbol)
        if fallback and fallback in history.columns:
            return fallback
        return None

    def generate_signals(
        self,
        date: pd.Timestamp,
        history: pd.DataFrame,
        open_positions: list[Position],
    ) -> list[Signal]:
        if self._bought:
            return []
        sym = self._resolve_symbol(history)
        if sym is None:
            return []
        # Need a valid price for this bar
        try:
            px = history[sym].loc[date]
        except KeyError:
            return []
        if not pd.notna(px) or px <= 0:
            return []
        self._actual_symbol = sym
        self._bought = True
        used_proxy = sym != self._symbol
        return [
            Signal(
                strategy_id=self._strategy_id,
                instruments=[sym],
                sides=["long"],
                target_sizes_eur=[self._initial_capital_eur],
                metadata={
                    "rationale": "initial_passive_position",
                    "configured_symbol": self._symbol,
                    "actual_symbol": sym,
                    "used_proxy": used_proxy,
                    "reinvest_dividends": True,
                },
            )
        ]

    def manage_positions(
        self,
        date: pd.Timestamp,
        history: pd.DataFrame,
        open_positions: list[Position],
    ) -> list[Action]:
        # Buy-and-hold: never sell. The engine will close at the end of the
        # backtest for accounting purposes ("eod" reason).
        return []
