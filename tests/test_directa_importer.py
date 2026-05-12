"""Smoke tests for the Directa XLSX importer and reconciliation engine.

The XLSX fixture (the user's real export) is gitignored, so these tests
self-skip when the file is absent — they only run on the developer's
machine after a fresh export.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from core.data.importers.directa_xlsx import (
    DirectaPortfolioSnapshot,
    DirectaPosition,
    DirectaXLSXImporter,
    import_directa_xlsx,
)
from portfolio.position_tracker import PositionTracker
from portfolio.reconciliation import apply_deltas, reconcile


_FIXTURE = Path("data_storage/imports/P_TOTALE_41141_20260512.xlsx")
_HAS_FIXTURE = _FIXTURE.exists()


# ---------- parser ----------


@pytest.mark.skipif(not _HAS_FIXTURE, reason="Directa XLSX fixture not present")
def test_parse_real_directa_export_metadata():
    snap = DirectaXLSXImporter().parse(_FIXTURE)
    assert snap.account == "41141"
    assert "MORICONI" in snap.account_holder
    # Loose bound — file values are known from manual inspection but the
    # test should survive future re-exports.
    assert snap.total_portfolio_value_eur > 100_000
    assert isinstance(snap.extraction_date, pd.Timestamp)


@pytest.mark.skipif(not _HAS_FIXTURE, reason="Directa XLSX fixture not present")
def test_parse_real_directa_export_positions():
    snap = DirectaXLSXImporter().parse(_FIXTURE)
    # 12 positions in the reference file: 10 bond rows, 2 equity rows.
    assert len(snap.positions) == 12
    by = snap.by_asset_class()
    assert len(by["bond"]) >= 8
    assert len(by["equity"]) >= 2
    # No unknowns on this file.
    assert by["unknown"] == []


@pytest.mark.skipif(not _HAS_FIXTURE, reason="Directa XLSX fixture not present")
def test_parser_classifies_us_treasury_as_bond():
    snap = DirectaXLSXImporter().parse(_FIXTURE)
    us_t = [p for p in snap.positions if p.isin == "US912810TA60"]
    assert us_t and us_t[0].asset_class == "bond"


@pytest.mark.skipif(not _HAS_FIXTURE, reason="Directa XLSX fixture not present")
def test_parser_classifies_us_stocks_as_equity():
    snap = DirectaXLSXImporter().parse(_FIXTURE)
    for isin in ("US0378331005", "US70450Y1038"):
        rows = [p for p in snap.positions if p.isin == isin]
        assert rows and rows[0].asset_class == "equity"


@pytest.mark.skipif(not _HAS_FIXTURE, reason="Directa XLSX fixture not present")
def test_cash_balance_optional_setter():
    snap = import_directa_xlsx(_FIXTURE, cash_balance_eur=34_877.0)
    assert snap.cash_balance_eur == 34_877.0
    assert snap.patrimony_total_eur == snap.total_portfolio_value_eur + 34_877.0


# ---------- reconciliation ----------


def _synthetic_snapshot() -> DirectaPortfolioSnapshot:
    bond = DirectaPosition(
        name="BTP TF 2,10% LG26 EUR",
        ticker="M.506794",
        isin="IT0005370306",
        price=99.974,
        quantity=5000.0,
        cost_basis_eur=4880.0,
        current_value_eur=4998.7,
        avg_purchase_price=97.6,
        pnl_eur=118.7,
        pnl_pct=2.43,
        currency="EUR",
        asset_class="bond",
        issuer="BTP",
    )
    equity = DirectaPosition(
        name="APPLE INC",
        ticker=".AAPL",
        isin="US0378331005",
        price=247.0,
        quantity=3.0,
        cost_basis_eur=472.01,
        current_value_eur=743.47,
        avg_purchase_price=157.34,
        pnl_eur=271.46,
        pnl_pct=57.51,
        currency="USD",
        asset_class="equity",
    )
    return DirectaPortfolioSnapshot(
        account="TEST",
        account_holder="TEST",
        extraction_date=pd.Timestamp.today().normalize(),
        total_portfolio_value_eur=5742.17,
        positions=[bond, equity],
    )


def test_reconcile_empty_tracker_marks_all_new():
    with tempfile.TemporaryDirectory() as td:
        tracker = PositionTracker(positions_path=Path(td) / "p.parquet")
        report = reconcile(_synthetic_snapshot(), tracker)
        assert report.n_new == 2
        assert report.n_updated == 0
        assert report.n_closed == 0


def test_reconcile_existing_unchanged():
    with tempfile.TemporaryDirectory() as td:
        tracker = PositionTracker(positions_path=Path(td) / "p.parquet")
        snap = _synthetic_snapshot()
        # Pre-load tracker with the exact same data.
        tracker.add_bond(
            isin=snap.positions[0].isin,
            name=snap.positions[0].name,
            quantity=snap.positions[0].quantity,
            avg_purchase_price=snap.positions[0].avg_purchase_price,
            purchase_date=pd.Timestamp.today().normalize(),
        )
        tracker.add_equity(
            isin=snap.positions[1].isin,
            name=snap.positions[1].name,
            quantity=snap.positions[1].quantity,
            avg_purchase_price=snap.positions[1].avg_purchase_price,
            purchase_date=pd.Timestamp.today().normalize(),
        )
        report = reconcile(snap, tracker)
        assert report.n_unchanged == 2
        assert report.n_new == 0


def test_apply_deltas_writes_only_accepted_rows():
    with tempfile.TemporaryDirectory() as td:
        tracker = PositionTracker(positions_path=Path(td) / "p.parquet")
        snap = _synthetic_snapshot()
        report = reconcile(snap, tracker)
        # Accept the bond, skip the equity.
        choices = {"IT0005370306": True, "US0378331005": False}
        stats = apply_deltas(report, tracker, choices)
        assert stats["applied_new"] == 1
        assert stats["skipped"] == 1
        # Tracker now has exactly the bond.
        actives = tracker.get_all()
        assert len(actives) == 1
        assert actives[0].isin == "IT0005370306"


def test_reconcile_detects_closed_position():
    with tempfile.TemporaryDirectory() as td:
        tracker = PositionTracker(positions_path=Path(td) / "p.parquet")
        # Tracker has a position the broker no longer reports.
        tracker.add_bond(
            isin="IT9999999999",
            name="Old bond",
            quantity=1000.0,
            avg_purchase_price=100.0,
            purchase_date=pd.Timestamp.today().normalize(),
        )
        snap = _synthetic_snapshot()
        report = reconcile(snap, tracker)
        assert report.n_closed == 1
        closed = report.by_type("closed")[0]
        assert closed.isin == "IT9999999999"
