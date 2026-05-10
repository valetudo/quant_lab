"""Strategies — list available strategies, status badge, README inline."""
from __future__ import annotations
from pathlib import Path

import streamlit as st

from quant_lab.ui.components.strategy_card import strategy_card

st.set_page_config(page_title="Strategies", page_icon="📈", layout="wide")
st.title("📈 Strategies")
st.caption("All strategies in the quant_lab monorepo.")

repo_root = Path(__file__).resolve().parents[2]

# Each entry: (id, status, instantiator, readme, tests_dir)
ENTRIES = [
    dict(
        id="bonds_income", status="working",
        readme=repo_root / "strategies" / "bonds_income" / "README.md",
        tests=repo_root / "strategies" / "bonds_income" / "tests",
        instantiate=lambda: __import__("quant_lab.strategies.bonds_income",
                                       fromlist=["BondsIncome"]).BondsIncome(bond_snapshot=[]),
    ),
    dict(
        id="quality_stocks", status="scaffold",
        readme=repo_root / "strategies" / "quality_stocks" / "README.md",
        tests=repo_root / "strategies" / "quality_stocks" / "tests",
        instantiate=lambda: __import__("quant_lab.strategies.quality_stocks",
                                       fromlist=["QualityStocks"]).QualityStocks(),
    ),
    dict(
        id="dummy_buy_and_hold", status="working",
        readme=repo_root / "strategies" / "_examples" / "README.md",
        tests=None,
        instantiate=lambda: __import__("quant_lab.strategies._examples",
                                       fromlist=["DummyBuyAndHold"]).DummyBuyAndHold(
                                           tickers=["AAPL", "MSFT"]),
    ),
]

for e in ENTRIES:
    try:
        inst = e["instantiate"]()
        u_size = len(inst.universe)
    except Exception as ex:
        st.error(f"failed to instantiate {e['id']}: {ex}")
        continue
    strategy_card(strategy_id=e["id"], status=e["status"],
                  universe_size=u_size,
                  readme_path=e["readme"], tests_path=e["tests"])
