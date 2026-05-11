"""Pattern Finder adapter — wraps the external pattern_finder repo.

STATUS: SCAFFOLDED. The strategy registers and instantiates without error
(important so the framework smoke tests don't crash), but
``generate_signals`` and ``manage_positions`` are no-ops until the external
repo is cloned and the signal-translation TODOs are filled in.

To activate:
  1. Clone the external repo to the path in config.yaml::pattern_finder_path
  2. Implement the TODOs in this file:
       - signal translation in ``generate_signals``
       - triple-barrier exit handling in ``manage_positions``
  3. Run walk-forward + benchmark comparison (see docs/adding_a_strategy.md)
  4. Flip ``status: active`` in config.yaml

The scaffold path is intentional: the adapter exists in the registry as
``status: scaffold``, the Portfolio Overview / Strategies page show it
explicitly as "not yet active", and the user has a clear single place to
work when ready.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from core.strategy.base import Strategy
from core.strategy.signals import Action, Position, Signal

log = logging.getLogger(__name__)


def _load_config(path: Optional[Path]) -> dict:
    if path is None:
        path = Path(__file__).resolve().parent / "config.yaml"
    if not Path(path).exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class PatternFinder(Strategy):
    """Adapter for the external Pattern Finder project.

    When ``status == 'scaffold'`` (the default), the adapter:
      - registers in the auto-discovery registry,
      - reports its universe from config,
      - returns no signals (no-op).

    When ``status == 'active'`` and the external path exists, it imports the
    external runner and translates its output to Quant Lab Signal/Action.
    """

    def __init__(
        self,
        *,
        config_path: Optional[Path] = None,
        external_runner: object = None,
    ) -> None:
        self.cfg = _load_config(config_path)
        self._strategy_id = self.cfg.get("strategy_id", "pattern_finder")
        self._status = self.cfg.get("status", "scaffold")
        self._external_path = self.cfg.get("pattern_finder_path")
        self._universe = list(self.cfg.get("universe", ["SPY"]))
        self._capital_per_trade = float(self.cfg.get("capital_per_trade_eur", 1000))
        self._forward_window = int(self.cfg.get("forward_window_days", 10))

        # Allow injection for tests (avoids touching the external repo)
        self._runner = external_runner

        if self._status == "active":
            self._activate()
        else:
            log.info("pattern_finder: scaffold status — generate_signals will return [].")

    # ---- activation logic ----

    def _activate(self) -> None:
        """When status='active', import the external runner.

        Raises RuntimeError if the external path is missing or unreadable —
        this is intentional: an "active" status with no runtime backing is
        worse than an explicit failure.
        """
        if self._runner is not None:
            return  # already injected (tests)
        if not self._external_path or not os.path.isdir(self._external_path):
            raise RuntimeError(
                f"pattern_finder is 'active' but external path "
                f"{self._external_path!r} does not exist. Clone the repo "
                f"or change config.yaml::status back to 'scaffold'."
            )
        if self._external_path not in sys.path:
            sys.path.insert(0, str(self._external_path))
        try:
            import importlib

            self._runner = importlib.import_module("runner")
        except ImportError as e:
            raise RuntimeError(
                f"pattern_finder external repo found at "
                f"{self._external_path} but no `runner` module: {e}"
            ) from e

    # ---- Strategy ABC ----

    @property
    def strategy_id(self) -> str:
        return self._strategy_id

    @property
    def universe(self) -> list[str]:
        return list(self._universe)

    def on_init(self, history: pd.DataFrame) -> None:
        if self._status != "active":
            return
        # TODO: forward to self._runner.on_init when activated
        return None

    def generate_signals(
        self,
        date: pd.Timestamp,
        history: pd.DataFrame,
        open_positions: list[Position],
    ) -> list[Signal]:
        if self._status != "active" or self._runner is None:
            return []
        # TODO: when activated, call self._runner.<entry-point>(date, history, ...)
        # and translate its output into Signal objects with:
        #   strategy_id=self._strategy_id,
        #   instruments=[symbol], sides=["long"],
        #   target_sizes_eur=[self._capital_per_trade],
        #   metadata={"pattern_id": ..., "score": ..., "forward_window_days": ...}
        return []

    def manage_positions(
        self,
        date: pd.Timestamp,
        history: pd.DataFrame,
        open_positions: list[Position],
    ) -> list[Action]:
        if self._status != "active" or self._runner is None:
            return []
        # TODO: when activated, implement the triple-barrier exit logic.
        # Read open positions' metadata for entry_date / forward_window and
        # close those that have hit the upper/lower barrier or the time
        # barrier. See pattern_finder repo docs for the rules.
        return []
