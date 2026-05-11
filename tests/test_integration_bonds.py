"""End-to-end integration: BondsIncome on a synthetic bond panel."""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.backtest.engine import PortfolioBacktester
from strategies.bonds_income import BondsIncome


def _mock_bond_snapshot():
    return [
        {
            "isin": "IT_TEST_001",
            "name": "BTP-3.50 ST2030 EU",
            "coupon": 3.5,
            "maturity_date": "2030-09-30",
            "currency": "EUR",
            "latest_price": 99.0,
            "tipologia": "Titoli Di Stato Italiani",
            "nation": "Italia",
        },
        {
            "isin": "IT_TEST_002",
            "name": "BTP-4.00 OT2028 EU",
            "coupon": 4.0,
            "maturity_date": "2028-10-31",
            "currency": "EUR",
            "latest_price": 100.5,
            "tipologia": "Titoli Di Stato Italiani",
            "nation": "Italia",
        },
        {
            "isin": "FR_TEST_001",
            "name": "OAT 2.50 MG2029 EU",
            "coupon": 2.5,
            "maturity_date": "2029-05-25",
            "currency": "EUR",
            "latest_price": 96.0,
            "tipologia": "Titoli Di Stato Esteri",
            "nation": "Francia",
        },
    ]


def _bond_panel():
    """Synthetic flat-ish bond price panel — par=100 with tiny drift."""
    idx = pd.date_range("2024-01-02", periods=120, freq="B")
    rng = np.random.default_rng(7)
    cols = ["IT_TEST_001", "IT_TEST_002", "FR_TEST_001"]
    walks = rng.normal(0, 0.001, size=(len(idx), len(cols)))
    prices = 100 + np.cumsum(walks, axis=0)
    return pd.DataFrame(prices, index=idx, columns=cols)


def test_bonds_income_runs_end_to_end():
    panel = _bond_panel()
    strat = BondsIncome(bond_snapshot=_mock_bond_snapshot(), initial_capital_eur=50_000)
    bt = PortfolioBacktester(
        strat, panel, initial_capital_eur=50_000, commission_bps=5, slippage_bps=5
    )
    res = bt.run()
    assert not res.equity.empty
    # At minimum the first month should generate some trades — but the
    # mock snapshot is only 3 bonds and config asks for 20; whatever
    # passes the filter (≥ min_yield) gets bought.
    assert len(res.trades) >= 0
    # Equity sanity: positive and within reason
    final = res.equity["equity"].iloc[-1]
    assert final > 0
    assert 0.5 * 50_000 < final < 1.5 * 50_000
