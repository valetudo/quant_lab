"""Strategy auto-discovery + registration.

Walks ``strategies/`` and registers every subpackage that ships:
  - a ``strategy.py`` module that defines exactly one (or one primary) class
    subclassing :class:`core.strategy.base.Strategy`, AND
  - a ``config.yaml`` (with at minimum a ``strategy_id`` key — falls back to
    the folder name).

Folders starting with ``_`` are skipped (``_archived``, ``_examples``,
``_legacy``, etc.).

The registry is used by:
  - ``ui/pages/2_Strategies.py`` — to list strategies grouped by sleeve.
  - ``ui/pages/3_Backtest_Runner.py`` — to populate the strategy dropdown.
  - ``portfolio.state.PortfolioState`` — to discover which strategies belong
    to the opportunistic sleeve dynamically.

Convention:

    strategies/<id>/
        __init__.py
        strategy.py        # class FooBar(Strategy): ...
        config.yaml        # strategy_id: foo_bar, status: active|scaffold|deprecated
        tests/
        README.md          # optional

Adding a new strategy requires zero core changes; restart Streamlit and it
appears.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from core.strategy.base import Strategy

log = logging.getLogger(__name__)


@dataclass
class StrategyInfo:
    """One registered strategy."""

    id: str
    cls: type
    module_path: str
    directory: str
    config: dict
    config_path: str
    description: str = ""
    status: str = "active"  # active | scaffold | deprecated
    sleeve: str = "opportunistic"  # bonds | equity | opportunistic
    readme_path: Optional[str] = None
    tests_path: Optional[str] = None

    def instantiate(self, **kwargs) -> Strategy:
        """Build an instance of the registered class.

        ``kwargs`` are forwarded to the class constructor. The registry never
        guesses arguments — callers are responsible for matching the
        constructor signature.
        """
        return self.cls(**kwargs)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_portfolio_yaml() -> dict:
    p = _repo_root() / "configs" / "portfolio.yaml"
    if not p.exists():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        log.warning("could not read portfolio.yaml: %s", e)
        return {}


class StrategyRegistry:
    """Scans ``strategies/`` once on construction. Re-instantiate to refresh."""

    def __init__(self, strategies_dir: Optional[Path] = None) -> None:
        self.strategies_dir = (
            Path(strategies_dir) if strategies_dir else _repo_root() / "strategies"
        )
        self._registry: dict[str, StrategyInfo] = {}
        self._portfolio_cfg = _load_portfolio_yaml()
        self._scan()

    # -------- discovery --------

    def _scan(self) -> None:
        if not self.strategies_dir.exists():
            log.warning("strategies dir not found: %s", self.strategies_dir)
            return
        for d in sorted(self.strategies_dir.iterdir()):
            if not d.is_dir() or d.name.startswith("_"):
                continue
            try:
                info = self._register_one(d)
                if info:
                    self._registry[info.id] = info
            except Exception as e:
                log.warning("registry: failed to register %s: %s", d.name, e)

    def _register_one(self, d: Path) -> Optional[StrategyInfo]:
        strategy_py = d / "strategy.py"
        config_yaml = d / "config.yaml"
        if not strategy_py.exists():
            return None

        # Config is optional — we fall back to folder name + defaults
        cfg: dict[str, Any] = {}
        if config_yaml.exists():
            try:
                cfg = yaml.safe_load(config_yaml.read_text(encoding="utf-8")) or {}
            except Exception as e:
                log.warning("registry: bad YAML in %s: %s", config_yaml, e)
        strategy_id = cfg.get("strategy_id") or d.name

        module_path = f"strategies.{d.name}.strategy"
        try:
            module = importlib.import_module(module_path)
        except Exception as e:
            log.warning("registry: import failed for %s: %s", module_path, e)
            return None

        # Find the strategy class — first concrete subclass of Strategy
        cls: Optional[type] = None
        for _, obj in inspect.getmembers(module):
            if (
                inspect.isclass(obj)
                and obj is not Strategy
                and issubclass(obj, Strategy)
                and obj.__module__ == module.__name__
            ):
                cls = obj
                break
        if cls is None:
            log.info("registry: no Strategy subclass in %s — skipping", module_path)
            return None

        readme = d / "README.md"
        tests = d / "tests"
        return StrategyInfo(
            id=strategy_id,
            cls=cls,
            module_path=module_path,
            directory=str(d),
            config=cfg,
            config_path=str(config_yaml) if config_yaml.exists() else "",
            description=str(cfg.get("description", "")).strip(),
            status=str(cfg.get("status", "active")).strip(),
            sleeve=self._infer_sleeve(strategy_id),
            readme_path=str(readme) if readme.exists() else None,
            tests_path=str(tests) if tests.exists() and tests.is_dir() else None,
        )

    def _infer_sleeve(self, strategy_id: str) -> str:
        sleeves = self._portfolio_cfg.get("sleeves", {})
        for sleeve_id, defn in sleeves.items():
            if strategy_id in (defn.get("strategy_ids") or []):
                return sleeve_id
        # default — anything not explicitly assigned goes to opportunistic
        return "opportunistic"

    # -------- queries --------

    def all(self) -> list[StrategyInfo]:
        return list(self._registry.values())

    def by_sleeve(self, sleeve: str) -> list[StrategyInfo]:
        return [s for s in self._registry.values() if s.sleeve == sleeve]

    def by_status(self, status: str) -> list[StrategyInfo]:
        return [s for s in self._registry.values() if s.status == status]

    def get(self, strategy_id: str) -> Optional[StrategyInfo]:
        return self._registry.get(strategy_id)

    def ids(self) -> list[str]:
        return list(self._registry.keys())

    def ids_by_sleeve(self, sleeve: str) -> list[str]:
        return [s.id for s in self.by_sleeve(sleeve)]

    def __contains__(self, strategy_id: str) -> bool:
        return strategy_id in self._registry

    def __len__(self) -> int:
        return len(self._registry)
