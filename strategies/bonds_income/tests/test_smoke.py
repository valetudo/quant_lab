"""Smoke test: BondsIncome instantiates and generates signals on mock data."""
from __future__ import annotations

import pandas as pd

from quant_lab.strategies.bonds_income import BondsIncome


def _mock_bonds():
    return [
        {
            "isin": "IT0000000001", "name": "BTP-3.00 ST2028 EU", "coupon": 3.0,
            "maturity_date": "2028-09-30", "currency": "EUR",
            "latest_price": 99.5, "tipologia": "Titoli Di Stato Italiani",
            "nation": "Italia",
        },
        {
            "isin": "IT0000000002", "name": "BTP-4.50 OT2030 EU", "coupon": 4.5,
            "maturity_date": "2030-10-31", "currency": "EUR",
            "latest_price": 101.2, "tipologia": "Titoli Di Stato Italiani",
            "nation": "Italia",
        },
        {
            "isin": "FR0000000003", "name": "OAT 2.50 MG2029 EU", "coupon": 2.5,
            "maturity_date": "2029-05-25", "currency": "EUR",
            "latest_price": 96.0, "tipologia": "Titoli Di Stato Esteri",
            "nation": "Francia",
        },
    ]


def test_bonds_income_instantiates_and_emits():
    strat = BondsIncome(bond_snapshot=_mock_bonds(), initial_capital_eur=10_000)
    # Build a 5-day "panel" carrying the ISINs as columns at par=100.
    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    panel = pd.DataFrame(100.0, index=idx, columns=["IT0000000001",
                                                    "IT0000000002",
                                                    "FR0000000003"])
    strat.on_init(panel.iloc[:1])
    sigs = strat.generate_signals(idx[0], panel.iloc[:1], [])
    # Each selected bond should produce one Signal with target_sizes_eur > 0.
    assert isinstance(sigs, list)
    for s in sigs:
        assert s.strategy_id == "bonds_income"
        assert len(s.instruments) == 1
        assert s.sides == ["long"]
        assert s.target_sizes_eur[0] > 0
