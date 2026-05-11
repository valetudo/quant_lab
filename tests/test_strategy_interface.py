"""Verify every concrete Strategy in the repo respects the ABC contract.

Quality Stocks was archived 2026-05-11 (see _migration_log/V5_VS_SPY_DECISION.md)
and is no longer exercised here. PassiveEquity (Phase 4 replacement) is.
"""

from __future__ import annotations


from core.strategy.base import Strategy
from strategies._examples import DummyBuyAndHold
from strategies.bonds_income import BondsIncome
from strategies.passive_equity import PassiveEquity

REQUIRED_METHODS = {"on_init", "generate_signals", "manage_positions"}
REQUIRED_PROPERTIES = {"strategy_id", "universe"}

ACTIVE_STRATEGIES = (DummyBuyAndHold, BondsIncome, PassiveEquity)


def _instance_for(cls):
    if cls is DummyBuyAndHold:
        return cls(tickers=["AAA"])
    if cls is BondsIncome:
        return cls(bond_snapshot=[])
    if cls is PassiveEquity:
        return cls(symbol="SPY", initial_capital_eur=10_000.0)
    return cls()


def test_all_strategies_subclass_abc():
    for cls in ACTIVE_STRATEGIES:
        assert issubclass(cls, Strategy), f"{cls.__name__} must subclass Strategy"


def test_all_strategies_implement_required_methods():
    for cls in ACTIVE_STRATEGIES:
        inst = _instance_for(cls)
        for m in REQUIRED_METHODS:
            assert callable(getattr(inst, m, None)), f"{cls.__name__} missing {m}"
        for p in REQUIRED_PROPERTIES:
            assert hasattr(inst, p), f"{cls.__name__} missing property {p}"


def test_strategy_id_is_str():
    for cls in ACTIVE_STRATEGIES:
        inst = _instance_for(cls)
        sid = inst.strategy_id
        assert isinstance(sid, str) and sid, f"{cls.__name__}.strategy_id must be non-empty str"
