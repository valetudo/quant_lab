"""Tests for portfolio.static_allocator + portfolio.state."""

from __future__ import annotations

import pytest

from portfolio.static_allocator import (
    SleeveDefinition,
    StaticPortfolio,
    StrategicAllocation,
)

# ---------- StrategicAllocation validation ----------


def test_strategic_allocation_must_sum_to_one():
    with pytest.raises(ValueError):
        StrategicAllocation(sleeve_targets={"a": 0.6, "b": 0.3})  # sums to 0.9


def test_strategic_allocation_rejects_negative():
    with pytest.raises(ValueError):
        StrategicAllocation(sleeve_targets={"a": 1.1, "b": -0.1})


def test_strategic_allocation_accepts_60_30_10():
    sa = StrategicAllocation(sleeve_targets={"bonds": 0.60, "equity": 0.30, "opportunistic": 0.10})
    assert sa.drift_threshold_pp == 5.0


# ---------- SleeveDefinition validation ----------


def test_sleeve_definition_strategy_weights_sum_to_one():
    with pytest.raises(ValueError):
        SleeveDefinition(
            sleeve_id="equity",
            strategy_ids=["qs"],
            strategy_weights={"qs": 0.5},  # < 1.0
            target_weight_of_total=0.30,
        )


def test_sleeve_definition_unknown_strategy_in_weights():
    with pytest.raises(ValueError):
        SleeveDefinition(
            sleeve_id="equity",
            strategy_ids=["qs"],
            strategy_weights={"qs": 0.5, "other": 0.5},  # 'other' not in strategy_ids
            target_weight_of_total=0.30,
        )


def test_sleeve_definition_accepts_empty_placeholder():
    """Opportunistic sleeve has no strategies wired yet — must be allowed."""
    sd = SleeveDefinition(
        sleeve_id="opportunistic",
        strategy_ids=[],
        strategy_weights={},
        target_weight_of_total=0.10,
    )
    assert sd.sleeve_id == "opportunistic"


# ---------- StaticPortfolio capital helpers ----------


def _make_portfolio(total: float = 100_000.0) -> StaticPortfolio:
    alloc = StrategicAllocation(
        sleeve_targets={"bonds": 0.60, "equity": 0.30, "opportunistic": 0.10}
    )
    sleeves = [
        SleeveDefinition(
            sleeve_id="bonds",
            strategy_ids=["bonds_income"],
            strategy_weights={"bonds_income": 1.0},
            target_weight_of_total=0.60,
        ),
        SleeveDefinition(
            sleeve_id="equity",
            strategy_ids=["passive_equity"],
            strategy_weights={"passive_equity": 1.0},
            target_weight_of_total=0.30,
        ),
        SleeveDefinition(
            sleeve_id="opportunistic",
            strategy_ids=[],
            strategy_weights={},
            target_weight_of_total=0.10,
        ),
    ]
    return StaticPortfolio(allocation=alloc, sleeves=sleeves, total_capital_eur=total)


def test_static_portfolio_sleeve_capital():
    sp = _make_portfolio(100_000.0)
    assert sp.get_sleeve_capital("bonds") == pytest.approx(60_000.0)
    assert sp.get_sleeve_capital("equity") == pytest.approx(30_000.0)
    assert sp.get_sleeve_capital("opportunistic") == pytest.approx(10_000.0)


def test_static_portfolio_strategy_capital():
    sp = _make_portfolio(100_000.0)
    assert sp.get_strategy_capital("equity", "passive_equity") == pytest.approx(30_000.0)
    assert sp.get_strategy_capital("bonds", "bonds_income") == pytest.approx(60_000.0)


def test_static_portfolio_validates_target_consistency():
    """SleeveDefinition.target_weight_of_total must match the allocation entry."""
    alloc = StrategicAllocation(sleeve_targets={"a": 1.0})
    sd = SleeveDefinition(
        sleeve_id="a", strategy_ids=["s"], strategy_weights={"s": 1.0}, target_weight_of_total=0.5
    )  # inconsistent
    with pytest.raises(ValueError):
        StaticPortfolio(allocation=alloc, sleeves=[sd], total_capital_eur=100.0)


# ---------- drift analysis ----------


def test_compute_drift_no_drift():
    sp = _make_portfolio(100_000.0)
    drift = sp.compute_drift({"bonds": 60_000, "equity": 30_000, "opportunistic": 10_000})
    for d in drift.values():
        assert abs(d["drift_pp"]) < 0.01
        assert d["alert"] is False


def test_compute_drift_with_alert_above_threshold():
    sp = _make_portfolio(100_000.0)
    # bonds at 70%, equity at 20%, opp at 10% — bonds drifted +10pp
    drift = sp.compute_drift({"bonds": 70_000, "equity": 20_000, "opportunistic": 10_000})
    assert drift["bonds"]["alert"] is True
    assert drift["bonds"]["drift_pp"] == pytest.approx(10.0)
    assert drift["equity"]["alert"] is True
    assert drift["equity"]["drift_pp"] == pytest.approx(-10.0)
    assert drift["opportunistic"]["alert"] is False


def test_compute_drift_small_drift_no_alert():
    sp = _make_portfolio(100_000.0)
    # bonds 62k, equity 28k, opp 10k — bonds +2pp, equity -2pp (under 5pp threshold)
    drift = sp.compute_drift({"bonds": 62_000, "equity": 28_000, "opportunistic": 10_000})
    assert all(not d["alert"] for d in drift.values())


# ---------- rebalance suggestions ----------


def test_rebalance_suggestions_concrete_amount():
    sp = _make_portfolio(100_000.0)
    drift_values = {"bonds": 70_000, "equity": 20_000, "opportunistic": 10_000}
    sugs = sp.rebalance_suggestions(drift_values)
    assert len(sugs) >= 1
    # bonds is over by 10k, equity short by 10k → suggest moving 10k from bonds to equity
    s = sugs[0]
    assert s["from_sleeve"] == "bonds"
    assert s["to_sleeve"] == "equity"
    assert s["amount_eur"] == pytest.approx(10_000.0, rel=1e-3)


def test_rebalance_suggestions_empty_when_on_target():
    sp = _make_portfolio(100_000.0)
    sugs = sp.rebalance_suggestions({"bonds": 60_000, "equity": 30_000, "opportunistic": 10_000})
    assert sugs == []
