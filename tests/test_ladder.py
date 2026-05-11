"""Tests for strategies.bonds_income.ladder + positions_io."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from strategies.bonds_income.ladder import (
    LadderConfig,
    LadderTracker,
)
from strategies.bonds_income.positions_io import (
    add_position,
    close_position,
    load_positions,
)

# ---------- LadderConfig validation ----------


def test_ladder_config_defaults():
    cfg = LadderConfig()
    assert cfg.maturity_buckets_years == (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
    assert cfg.sovereign_weight == 0.70
    assert cfg.corporate_weight == 0.30
    assert cfg.min_rating_corporate == "BBB-"
    assert cfg.liquidity_reserve_pct == 5.0


def test_ladder_config_rejects_bad_mix():
    with pytest.raises(ValueError):
        LadderConfig(sovereign_weight=0.5, corporate_weight=0.4)


def test_ladder_config_rejects_non_ig_rating():
    with pytest.raises(ValueError):
        LadderConfig(min_rating_corporate="BB+")


def test_bucket_label_boundaries():
    cfg = LadderConfig()
    assert cfg.bucket_label(0.5) == "1y"
    assert cfg.bucket_label(1.0) == "1y"
    assert cfg.bucket_label(1.0001) == "2y"
    assert cfg.bucket_label(4.9) == "5y"
    assert cfg.bucket_label(5.0) == "5y"
    assert cfg.bucket_label(10.0) == "10y"
    assert cfg.bucket_label(11.0) == ">10y"


# ---------- positions_io ----------


def test_load_positions_missing_file_returns_empty(tmp_path):
    df = load_positions(tmp_path / "no.parquet")
    assert df.empty
    # All schema columns must be present
    for c in ("isin", "status", "current_market_value_eur", "maturity_date"):
        assert c in df.columns


def test_add_and_load_roundtrip(tmp_path):
    p = tmp_path / "positions.parquet"
    add_position(
        path=p,
        isin="IT0001",
        description="BTP 1y",
        quantity=10_000,
        avg_purchase_price=99.5,
        purchase_date=date(2025, 1, 15),
        coupon=3.0,
        maturity_date=date(2026, 1, 15),
        ytm_at_purchase=3.5,
        nation="Italia",
        issuer_type="Government",
    )
    df = load_positions(p)
    assert len(df) == 1
    assert df.iloc[0]["isin"] == "IT0001"
    assert df.iloc[0]["status"] == "active"
    assert df.iloc[0]["current_market_value_eur"] == pytest.approx(9950.0)


def test_add_position_duplicate_isin_raises(tmp_path):
    p = tmp_path / "positions.parquet"
    add_position(
        path=p,
        isin="IT0001",
        description="BTP",
        quantity=1000,
        avg_purchase_price=100.0,
        purchase_date=date(2025, 1, 1),
        coupon=3.0,
        maturity_date=date(2030, 1, 1),
        ytm_at_purchase=3.0,
    )
    with pytest.raises(ValueError):
        add_position(
            path=p,
            isin="IT0001",
            description="BTP",
            quantity=1000,
            avg_purchase_price=100.0,
            purchase_date=date(2025, 1, 1),
            coupon=3.0,
            maturity_date=date(2030, 1, 1),
            ytm_at_purchase=3.0,
        )


def test_close_position_marks_status(tmp_path):
    p = tmp_path / "positions.parquet"
    add_position(
        path=p,
        isin="IT0001",
        description="BTP",
        quantity=1000,
        avg_purchase_price=100.0,
        purchase_date=date(2025, 1, 1),
        coupon=3.0,
        maturity_date=date(2030, 1, 1),
        ytm_at_purchase=3.0,
    )
    close_position("IT0001", reason="sold", closed_price=101.5, path=p)
    df = load_positions(p)
    assert df.iloc[0]["status"] == "sold"
    assert df.iloc[0]["closed_price"] == pytest.approx(101.5)


# ---------- LadderTracker.get_gaps ----------


def _ladder_with_full_rolling(tmp_path: Path) -> LadderTracker:
    """Populate an ideal rolling 1-10y ladder, equal weight, ~10k per bucket."""
    today = date.today()
    for n in range(1, 11):
        add_position(
            path=tmp_path / "p.parquet",
            isin=f"IT{n:04d}",
            description=f"BTP {n}y",
            quantity=10_000,
            avg_purchase_price=100.0,
            purchase_date=today,
            coupon=3.0,
            maturity_date=today + timedelta(days=int(365 * n)),
            ytm_at_purchase=3.0,
            nation="Italia",
            issuer_type="Government",
        )
    return LadderTracker(positions_path=tmp_path / "p.parquet")


def test_get_gaps_empty_ladder_returns_empty(tmp_path):
    t = LadderTracker(positions_path=tmp_path / "p.parquet")
    # With no positions, all buckets have value 0, total_value=0,
    # so gap_eur = 0 - 0 = 0 → no gaps.
    assert t.get_gaps() == []


def test_get_gaps_full_ladder_no_gaps(tmp_path):
    t = _ladder_with_full_rolling(tmp_path)
    gaps = t.get_gaps()
    assert gaps == []


def test_get_gaps_missing_5y_bucket(tmp_path):
    """Populate 1-10y except the 5y bucket → expect a 5y suggestion."""
    today = date.today()
    p = tmp_path / "p.parquet"
    for n in range(1, 11):
        if n == 5:
            continue
        add_position(
            path=p,
            isin=f"IT{n:04d}",
            description=f"BTP {n}y",
            quantity=10_000,
            avg_purchase_price=100.0,
            purchase_date=today,
            coupon=3.0,
            maturity_date=today + timedelta(days=int(365 * n)),
            ytm_at_purchase=3.0,
            nation="Italia",
            issuer_type="Government",
        )
    t = LadderTracker(positions_path=p)
    gaps = t.get_gaps()
    bucket_ids = {g["bucket"] for g in gaps}
    assert "5y" in bucket_ids


# ---------- cash flow projection ----------


def test_cashflow_projection_3_bonds(tmp_path):
    """Synthetic 3-bond ladder maturing 1y, 5y, 10y from today."""
    today = date(2025, 6, 15)
    p = tmp_path / "p.parquet"
    for n in (1, 5, 10):
        add_position(
            path=p,
            isin=f"IT{n:04d}",
            description=f"BTP {n}y",
            quantity=10_000,
            avg_purchase_price=100.0,
            purchase_date=today,
            coupon=3.0,
            maturity_date=date(today.year + n, 6, 15),
            ytm_at_purchase=3.0,
            nation="Italia",
            issuer_type="Government",
        )
    t = LadderTracker(positions_path=p)
    # 2 years = 104 weeks horizon → 1y bond matures and pays coupon, 5y/10y pay coupons
    cf_2y = t.get_cash_flow_projection(horizon_weeks=104, today=today)
    assert not cf_2y.empty
    assert "type" in cf_2y.columns
    # Expect at least one maturity event (the 1y bond)
    assert (cf_2y["type"] == "maturity").any()
    # Expect coupon events
    assert (cf_2y["type"] == "coupon").any()


# ---------- candidate suggestions ----------


def test_suggest_candidates_filters_bucket_and_sorts_yield(tmp_path):
    """Mock screener with 3 candidates — only the one in the 5y bucket should be
    returned (plus optionally one in a neighbour bucket if mis-classified)."""
    cfg = LadderConfig()
    t = LadderTracker(config=cfg, positions_path=tmp_path / "empty.parquet")
    screener = pd.DataFrame(
        [
            # 2.5y → falls in 3y bucket
            {
                "isin": "X1",
                "name": "Bond 2.5y",
                "years_to_maturity": 2.5,
                "net_yield_pa": 2.5,
                "currency": "EUR",
                "issuer_type": "Government",
                "is_callable": False,
                "inflation_linked": False,
            },
            # 4.5y → falls in 5y bucket
            {
                "isin": "X2",
                "name": "Bond 4.5y",
                "years_to_maturity": 4.5,
                "net_yield_pa": 3.2,
                "currency": "EUR",
                "issuer_type": "Government",
                "is_callable": False,
                "inflation_linked": False,
            },
            # 4.8y → also 5y bucket, higher yield → should rank above X2
            {
                "isin": "X3",
                "name": "Bond 4.8y",
                "years_to_maturity": 4.8,
                "net_yield_pa": 3.8,
                "currency": "EUR",
                "issuer_type": "Government",
                "is_callable": False,
                "inflation_linked": False,
            },
        ]
    )
    out = t.suggest_candidates_for_bucket("5y", screener, n_suggestions=5)
    assert list(out["isin"]) == ["X3", "X2"]


def test_suggest_candidates_excludes_callable_and_inflation_linked(tmp_path):
    cfg = LadderConfig()
    t = LadderTracker(config=cfg, positions_path=tmp_path / "empty.parquet")
    screener = pd.DataFrame(
        [
            {
                "isin": "X1",
                "name": "Callable 5y",
                "years_to_maturity": 4.5,
                "net_yield_pa": 5.0,
                "currency": "EUR",
                "issuer_type": "Corporate",
                "rating": "A",
                "is_callable": True,
                "inflation_linked": False,
            },
            {
                "isin": "X2",
                "name": "Inflation 5y",
                "years_to_maturity": 4.5,
                "net_yield_pa": 4.0,
                "currency": "EUR",
                "issuer_type": "Government",
                "is_callable": False,
                "inflation_linked": True,
            },
            {
                "isin": "X3",
                "name": "OK 5y",
                "years_to_maturity": 4.5,
                "net_yield_pa": 3.2,
                "currency": "EUR",
                "issuer_type": "Government",
                "is_callable": False,
                "inflation_linked": False,
            },
        ]
    )
    out = t.suggest_candidates_for_bucket("5y", screener)
    assert list(out["isin"]) == ["X3"]


# ---------- health check ----------


def test_health_check_empty_ladder(tmp_path):
    t = LadderTracker(positions_path=tmp_path / "p.parquet")
    h = t.health_check()
    assert h["score"] == 0.0
    assert h["metrics"]["n_positions"] == 0
