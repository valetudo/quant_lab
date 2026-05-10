"""BondsIncome — monthly-rebalanced buy-and-hold sovereign bond income (MVP).

Logic:
  - On first bar AND first trading day of each month: read the bond
    universe, enrich + filter + rank by net yield, pick top N.
  - For each selected bond not already held: emit Signal(open). For each
    currently-held bond not in the new top N: emit Action(close).
  - Equal-weight sizing across the N selected bonds.
  - No leverage, no shorting, no derivatives.

Important caveats:
  - The MVP does NOT yet backtest with realistic BTP price history —
    `panel` here is expected to be a wide DataFrame of bond prices
    indexed by date and columned by ISIN. In Phase 1 the panel can be
    a synthetic constant (e.g. par=100) just to exercise the engine.
  - Yields come from the live bonds DB. For a proper historical
    backtest of the strategy itself, BTP price history must be loaded
    (Phase 2 task).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from quant_lab.core.strategy.base import Strategy
from quant_lab.core.strategy.signals import Action, Position, Signal
from quant_lab.core.strategy.lifecycle import is_first_of_month
from quant_lab.strategies.bonds_income.selection import enrich_and_select

log = logging.getLogger(__name__)


def _load_config(path: Optional[Path]) -> dict:
    p = Path(path) if path else Path(__file__).resolve().parent / "config.yaml"
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class BondsIncome(Strategy):
    def __init__(
        self,
        *,
        config_path: Optional[Path] = None,
        bonds_provider=None,
        bond_snapshot: Optional[list[dict]] = None,
        initial_capital_eur: float = 50_000.0,
        strategy_id: str = "bonds_income",
    ) -> None:
        self._strategy_id = strategy_id
        self.cfg = _load_config(config_path)
        self._initial_capital_eur = float(initial_capital_eur)

        # Strategy can be initialized with EITHER a live provider (queries
        # the DB at each rebalance — useful for live signals) OR a snapshot
        # list of bond dicts (deterministic backtests).
        self._provider = bonds_provider
        self._snapshot = list(bond_snapshot) if bond_snapshot is not None else None
        self._universe_cache: list[str] = []
        self._last_rebalance_month: Optional[tuple[int, int]] = None
        self._selected_now: list[dict] = []  # last selection, used by universe property

    # ---- Strategy ABC ----------------------------------------------------

    @property
    def strategy_id(self) -> str:
        return self._strategy_id

    @property
    def universe(self) -> list[str]:
        return list(self._universe_cache)

    def on_init(self, history: pd.DataFrame) -> None:
        self._last_rebalance_month = None
        self._selected_now = []
        # Pre-warm the universe cache for callers that ask before run().
        try:
            picks = self._select()
            self._universe_cache = [b["isin"] for b in picks]
            self._selected_now = picks
        except Exception as e:
            log.warning("on_init selection failed: %s", e)

    # ---- selection -------------------------------------------------------

    def _raw_bonds(self) -> list[dict]:
        if self._snapshot is not None:
            return list(self._snapshot)
        if self._provider is None:
            return []
        return self._provider.list_bonds(enrich=False)

    def _select(self) -> list[dict]:
        cfg = self.cfg
        return enrich_and_select(
            self._raw_bonds(),
            n_bonds=int(cfg.get("n_bonds", 20)),
            sovereign_only=bool(cfg.get("sovereign_only", True)),
            currency=str(cfg.get("currency", "EUR")),
            min_yield_pct=float(cfg.get("min_yield_pct", 2.0)),
            max_duration_years=float(cfg.get("max_duration_years", 8.0)),
            min_years_to_maturity=float(cfg.get("min_years_to_maturity", 0.75)),
            exclude_callable=bool(cfg.get("exclude_callable", True)),
            exclude_inflation_linked=bool(cfg.get("exclude_inflation_linked", True)),
        )

    def _due_for_rebalance(self, date: pd.Timestamp, history: pd.DataFrame) -> bool:
        freq = self.cfg.get("rebalance_freq", "monthly")
        if freq == "monthly":
            return is_first_of_month(date, history)
        if freq == "weekly":
            return date.weekday() == 0
        if freq == "quarterly":
            return date.month in (1, 4, 7, 10) and is_first_of_month(date, history)
        return is_first_of_month(date, history)

    # ---- engine hooks ----------------------------------------------------

    def generate_signals(
        self,
        date: pd.Timestamp,
        history: pd.DataFrame,
        open_positions: list[Position],
    ) -> list[Signal]:
        # Open initial positions on first bar; otherwise only at rebalance day.
        first_bar = len(history) == 1
        if not first_bar and not self._due_for_rebalance(date, history):
            return []
        picks = self._select()
        if not picks:
            return []
        self._selected_now = picks
        self._universe_cache = [b["isin"] for b in picks]

        held_isins = {p.instruments[0] for p in open_positions if p.instruments}
        new_isins = {b["isin"] for b in picks} - held_isins
        if not new_isins:
            return []

        # Equal-weight sizing: split the *currently uninvested* nominal
        # equally across new picks. Phase 1 approximation.
        per_leg = self._initial_capital_eur / max(len(picks), 1)
        signals: list[Signal] = []
        for b in picks:
            if b["isin"] not in new_isins:
                continue
            # Skip if no price in the panel — engine will reject anyway.
            if b["isin"] not in history.columns:
                continue
            if not pd.notna(history[b["isin"]].iloc[-1]):
                continue
            signals.append(Signal(
                strategy_id=self._strategy_id,
                instruments=[b["isin"]],
                sides=["long"],
                target_sizes_eur=[per_leg],
                metadata=dict(
                    name=b.get("name"),
                    net_yield_pct=b.get("net_yield_pa"),
                    years_to_maturity=b.get("years_to_maturity"),
                    nation=b.get("sovereign_nation"),
                    issuer_type=b.get("issuer_type"),
                    rebalance_date=str(date.date()) if hasattr(date, "date") else str(date),
                ),
            ))
        return signals

    def manage_positions(
        self,
        date: pd.Timestamp,
        history: pd.DataFrame,
        open_positions: list[Position],
    ) -> list[Action]:
        # On rebalance day: close positions that no longer make the top N.
        if not self._due_for_rebalance(date, history):
            return []
        if not self._selected_now:
            return []
        new_isins = {b["isin"] for b in self._selected_now}
        actions: list[Action] = []
        for pos in open_positions:
            if pos.strategy_id != self._strategy_id:
                continue
            if pos.instruments and pos.instruments[0] not in new_isins:
                actions.append(Action(
                    position_id=pos.position_id,
                    action="close",
                    reason="rebalance_drop",
                ))
        return actions
