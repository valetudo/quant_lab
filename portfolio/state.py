"""Portfolio state — loads config, knows current sleeve values, suggests rebalances.

Reads from:
  - ``configs/portfolio.yaml``                              (sleeve targets + total capital)
  - ``data_storage/bonds/positions.parquet``                (live bond ladder; written by Bond Ladder UI)
  - ``outputs/<strategy>/<window>/metrics_std.json``        (latest backtest equity for each strategy)
  - ``data_storage/portfolio/rebalance_log.jsonl``          (audit log of manual rebalances)

The "current sleeve value" definition deliberately mixes sources:
  - bonds sleeve  : market value of the ladder if present (manual entry),
                    else fall back to the target capital
  - equity sleeve : final_equity of the most recent backtest if present,
                    else target capital
  - opportunistic : 0 unless a strategy is wired in

This is intentionally a soft fallback so the UI is useful from the very first
day before any positions are entered.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import yaml

from portfolio.static_allocator import (
    SleeveDefinition,
    StaticPortfolio,
    StrategicAllocation,
)

log = logging.getLogger(__name__)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


class PortfolioState:
    """Stateful façade — load config once, then call ``refresh()`` to recompute."""

    def __init__(self, config_path: Optional[str | Path] = None) -> None:
        self.config_path = (
            Path(config_path) if config_path else _repo_root() / "configs" / "portfolio.yaml"
        )
        self.cfg: dict = {}
        self.portfolio: Optional[StaticPortfolio] = None
        self._load_config()

    # -------- config --------

    def _load_config(self) -> None:
        if not self.config_path.exists():
            raise FileNotFoundError(f"portfolio config not found: {self.config_path}")
        self.cfg = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        alloc = StrategicAllocation(
            sleeve_targets={k: float(v) for k, v in self.cfg["strategic_allocation"].items()},
            drift_threshold_pp=float(self.cfg.get("drift_threshold_pp", 5.0)),
        )
        sleeves = []
        for sid, s in self.cfg.get("sleeves", {}).items():
            sleeves.append(
                SleeveDefinition(
                    sleeve_id=sid,
                    strategy_ids=list(s.get("strategy_ids", [])),
                    strategy_weights={
                        k: float(v) for k, v in (s.get("strategy_weights") or {}).items()
                    },
                    target_weight_of_total=alloc.sleeve_targets[sid],
                    notes=str(s.get("notes", "")).strip(),
                )
            )
        self.portfolio = StaticPortfolio(
            allocation=alloc,
            sleeves=sleeves,
            total_capital_eur=float(self.cfg.get("total_capital_eur", 100_000.0)),
        )

    # -------- current sleeve values --------

    def get_current_sleeve_values(self) -> Dict[str, float]:
        """Best-effort EUR value per sleeve. Falls back to the target capital
        when no live positions / backtest outputs exist yet.
        """
        assert self.portfolio is not None
        out: Dict[str, float] = {}
        out["bonds"] = self._bonds_sleeve_value()
        out["equity"] = self._equity_sleeve_value()
        out["opportunistic"] = self._opportunistic_sleeve_value()
        return out

    def _bonds_sleeve_value(self) -> float:
        """Market value of bond ladder positions (if any)."""
        path = _repo_root() / "data_storage" / "bonds" / "positions.parquet"
        if not path.exists():
            return self.portfolio.get_sleeve_capital("bonds")
        try:
            df = pd.read_parquet(path)
        except Exception as e:
            log.warning("could not read bond positions: %s", e)
            return self.portfolio.get_sleeve_capital("bonds")
        if df.empty:
            return self.portfolio.get_sleeve_capital("bonds")
        active = df[df["status"] == "active"] if "status" in df.columns else df
        if "current_market_value_eur" in active.columns:
            v = float(active["current_market_value_eur"].fillna(0).sum())
            if v > 0:
                return v
        # Compute from price × quantity / 100 (% of face) if columns available
        if {"quantity", "current_price"}.issubset(active.columns):
            v = float((active["quantity"] * active["current_price"] / 100.0).fillna(0).sum())
            if v > 0:
                return v
        return self.portfolio.get_sleeve_capital("bonds")

    def _equity_sleeve_value(self) -> float:
        """Live equity sleeve value.

        Phase 4: the equity sleeve is passive (CSPX via passive_equity strategy).
        We mark-to-market by scaling the target capital by the change in the
        configured ETF (or its SPY proxy) since some "entry date". For now we
        use the first available date in the parquet — i.e. an as-if "bought at
        the start of available data" mark, which is a soft fallback until the
        user records an actual purchase date in a positions ledger.
        """
        target = self.portfolio.get_sleeve_capital("equity")
        # Read the passive_equity config for the ETF symbol
        sym = "CSPX.L"
        cfg = self.cfg.get("strategy_configs", {}).get("passive_equity", {})
        cfg_path = cfg.get("config_path")
        if cfg_path:
            full = _repo_root() / cfg_path
            if full.exists():
                try:
                    pe_cfg = yaml.safe_load(full.read_text(encoding="utf-8")) or {}
                    sym = pe_cfg.get("symbol", sym)
                except Exception:
                    pass

        # Try the symbol via DataStorage (with retail-proxy fallback)
        try:
            from core.data.storage import DataStorage, load_global_config

            storage = DataStorage.from_config(load_global_config())
            df = storage.get_prices_with_proxy(sym)
        except Exception:
            return target
        if df is None or df.empty or "adj_close" not in df.columns:
            return target

        prices = df["adj_close"].dropna()
        if len(prices) < 2:
            return target
        ret = float(prices.iloc[-1] / prices.iloc[0])
        return float(target * ret)

    def _opportunistic_sleeve_value(self) -> float:
        """Sum live values of any opportunistic strategies on the registry."""
        target = self.portfolio.get_sleeve_capital("opportunistic")
        try:
            from core.strategy.registry import StrategyRegistry

            registry = StrategyRegistry()
        except Exception:
            return target
        active_opp = [s for s in registry.by_sleeve("opportunistic") if s.status == "active"]
        if not active_opp:
            # No active opportunistic strategies — capital sits as cash at target
            return target
        # MVP: split the target capital equally — until per-strategy state ledgers
        # exist, treat opportunistic positions as held at face value.
        return target

    # -------- registry passthrough --------

    def get_opportunistic_strategies(self) -> list[dict]:
        """All strategies the registry assigns to the opportunistic sleeve.

        Returns a list of plain dicts (id, status, description, sleeve) so
        the UI can render without importing the registry directly.
        """
        try:
            from core.strategy.registry import StrategyRegistry

            registry = StrategyRegistry()
        except Exception as e:
            log.warning("registry load failed: %s", e)
            return []
        return [
            {
                "id": s.id,
                "status": s.status,
                "description": s.description,
                "sleeve": s.sleeve,
                "directory": s.directory,
                "readme_path": s.readme_path,
            }
            for s in registry.by_sleeve("opportunistic")
        ]

    # -------- analysis --------

    def get_drift_analysis(self) -> dict:
        values = self.get_current_sleeve_values()
        return self.portfolio.compute_drift(values)

    def get_rebalance_suggestions(self) -> list[dict]:
        values = self.get_current_sleeve_values()
        return self.portfolio.rebalance_suggestions(values)

    # -------- audit log --------

    def _audit_path(self) -> Path:
        p = _repo_root() / "data_storage" / "portfolio" / "rebalance_log.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def log_rebalance_event(self, description: str, payload: Optional[dict] = None) -> None:
        entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "description": description,
            "payload": dict(payload or {}),
        }
        with self._audit_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def read_rebalance_log(self, *, limit: int = 50) -> list[dict]:
        p = self._audit_path()
        if not p.exists():
            return []
        out: list[dict] = []
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out[-limit:][::-1]
