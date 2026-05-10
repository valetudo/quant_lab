"""Verify every concrete Strategy in the repo respects the ABC contract."""
from __future__ import annotations

import inspect

from quant_lab.core.strategy.base import Strategy
from quant_lab.strategies._examples import DummyBuyAndHold
from quant_lab.strategies.bonds_income import BondsIncome
from quant_lab.strategies.quality_stocks import QualityStocks


REQUIRED_METHODS = {"on_init", "generate_signals", "manage_positions"}
REQUIRED_PROPERTIES = {"strategy_id", "universe"}


def _instance_for(cls):
    if cls is DummyBuyAndHold:
        return cls(tickers=["AAA"])
    if cls is BondsIncome:
        return cls(bond_snapshot=[])
    return cls()


def test_all_strategies_subclass_abc():
    for cls in (DummyBuyAndHold, BondsIncome, QualityStocks):
        assert issubclass(cls, Strategy), f"{cls.__name__} must subclass Strategy"


def test_all_strategies_implement_required_methods():
    for cls in (DummyBuyAndHold, BondsIncome, QualityStocks):
        inst = _instance_for(cls)
        for m in REQUIRED_METHODS:
            assert callable(getattr(inst, m, None)), f"{cls.__name__} missing {m}"
        for p in REQUIRED_PROPERTIES:
            assert hasattr(inst, p), f"{cls.__name__} missing property {p}"


def test_strategy_id_is_str():
    for cls in (DummyBuyAndHold, BondsIncome, QualityStocks):
        inst = _instance_for(cls)
        sid = inst.strategy_id
        assert isinstance(sid, str) and sid, f"{cls.__name__}.strategy_id must be non-empty str"
