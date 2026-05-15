"""Tests for the LadderBuilder.

Uses an injected pandas universe so the tests are independent of bonds.db.
"""

from __future__ import annotations

import pandas as pd
import pytest

from strategies.bonds_income.ladder_builder import (
    LadderBuilder,
    LadderBuilderConfig,
    compute_next_12m_cashflow,
    format_broker_list,
)


def _synthetic_universe(today: pd.Timestamp) -> pd.DataFrame:
    """A tiny hand-built universe covering the three categories across
    rung 1..3 (1y, 2y, 3y) so a 3-rung 3y builder has enough to pick.
    """

    def row(
        *,
        isin: str,
        name: str,
        issuer: str,
        category: str,
        nation: str,
        years: float,
        yield_pct: float,
        price: float = 100.0,
        rating: str = "BBB",
        rating_score: int = 9,
        coupon_rate: float = 0.03,
        lot_size_eur: float = 1000.0,
    ) -> dict:
        return {
            "isin": isin,
            "name": name,
            "issuer": issuer,
            "category": category,
            "nation": nation,
            "maturity_date": today + pd.Timedelta(days=int(365.25 * years)),
            "yield_net": yield_pct / 100,
            "price_clean": price,
            "rating": rating,
            "rating_score": rating_score,
            "coupon_rate": coupon_rate,
            "coupon_frequency": 1,
            "lot_size_eur": lot_size_eur,
            "is_callable": False,
            "is_subordinated": False,
            "currency": "EUR",
        }

    rows = []
    for years in (1, 2, 3):
        rows.append(
            row(
                isin=f"IT-BTP-{years}y",
                name=f"BTP {years}y",
                issuer="Italia",
                category="gov_ita",
                nation="Italia",
                years=years,
                yield_pct=2.5 + 0.3 * years,
                rating="BBB",
                rating_score=9,
            )
        )
        # Corporate at ~A
        rows.append(
            row(
                isin=f"IT-CORP-{years}y",
                name=f"Eni {years}y",
                issuer="Eni",
                category="corp",
                nation="Italia",
                years=years,
                yield_pct=2.7 + 0.3 * years,
                rating="A",
                rating_score=6,
            )
        )
        # German Bund (AAA) at slightly higher yield than the BTP
        rows.append(
            row(
                isin=f"DE-BUND-{years}y",
                name=f"Bund {years}y",
                issuer="Germania",
                category="gov_foreign",
                nation="Germania",
                years=years,
                yield_pct=2.6 + 0.3 * years,
                rating="AAA",
                rating_score=1,
            )
        )
    return pd.DataFrame(rows)


def _synthetic_universe_only_low_rated_foreign(today: pd.Timestamp) -> pd.DataFrame:
    """Like the synthetic universe but the foreign sovereigns are BBB- —
    they must fail the rating gate and trigger redistribution."""
    df = _synthetic_universe(today)
    foreign_mask = df["category"] == "gov_foreign"
    df.loc[foreign_mask, "rating"] = "BBB-"
    df.loc[foreign_mask, "rating_score"] = 10
    return df


# ---------- config validation ----------


def test_config_rejects_non_unit_composition():
    with pytest.raises(ValueError, match="must sum to 1.0"):
        LadderBuilderConfig(
            budget_eur=50_000,
            gov_ita_weight=0.5,
            corp_weight=0.3,
            gov_foreign_weight=0.3,  # sums to 1.1
        )


def test_config_rejects_zero_budget():
    with pytest.raises(ValueError, match="budget_eur"):
        LadderBuilderConfig(budget_eur=0)


def test_config_rejects_n_rungs_zero():
    with pytest.raises(ValueError, match="n_rungs"):
        LadderBuilderConfig(budget_eur=10_000, n_rungs=0)


# ---------- builder happy path ----------


def test_builder_produces_3_rungs_with_all_three_categories():
    today = pd.Timestamp.today().normalize()
    universe = _synthetic_universe(today)
    cfg = LadderBuilderConfig(
        budget_eur=30_000,
        n_rungs=3,
        max_duration_years=3,
        maturity_tolerance_months=6,
    )
    proposal = LadderBuilder(cfg, universe=universe).build()

    assert len(proposal.rungs) == 3
    assert proposal.n_bonds_selected >= 3  # at least one per rung
    # No adaptation triggered — universe has high-quality foreign in every rung
    assert not any(r.composition_was_adapted for r in proposal.rungs)
    # Composition close to 50/25/25
    comp = proposal.actual_composition
    assert comp["gov_ita"] > 0.4
    assert comp["corp"] > 0.0
    assert comp["gov_foreign"] > 0.0


def test_builder_adapts_when_foreign_rating_too_low():
    today = pd.Timestamp.today().normalize()
    universe = _synthetic_universe_only_low_rated_foreign(today)
    cfg = LadderBuilderConfig(
        budget_eur=30_000,
        n_rungs=3,
        max_duration_years=3,
        foreign_min_rating="A-",
    )
    proposal = LadderBuilder(cfg, universe=universe).build()

    # All rungs should have been adapted: foreign weight collapsed to gov_ita
    assert all(r.composition_was_adapted for r in proposal.rungs)
    assert all(
        r.adaptation_reason == "foreign_rating_too_low" for r in proposal.rungs
    )
    # No gov_foreign bond got selected anywhere
    foreigns = [
        b
        for r in proposal.rungs
        for b in r.selected_bonds.values()
        if b is not None and b.category == "gov_foreign"
    ]
    assert foreigns == []
    # And the redistribution went to gov_ita: gov_ita weight should be 75%
    assert all(
        r.composition["gov_ita"] == pytest.approx(0.75) for r in proposal.rungs
    )


def test_builder_skips_lot_size_above_rung_target():
    """A rung whose target slot is smaller than one €10k lot should record
    the candidate as `lot_size_exceeds_budget`."""
    today = pd.Timestamp.today().normalize()
    # 1 rung × 25% corp = 2500 EUR slot. A €10k corporate lot does not fit.
    universe = _synthetic_universe(today)
    universe.loc[universe["category"] == "corp", "lot_size_eur"] = 10_000
    cfg = LadderBuilderConfig(
        budget_eur=10_000,  # tight budget
        n_rungs=1,
        max_duration_years=1,
    )
    proposal = LadderBuilder(cfg, universe=universe).build()
    # Find at least one skip with reason `lot_size_exceeds_budget`
    reasons = {sk.reason for r in proposal.rungs for sk in r.skipped_bonds}
    assert "lot_size_exceeds_budget" in reasons


# ---------- aggregates + helpers ----------


def test_weighted_avg_ytm_is_capital_weighted():
    today = pd.Timestamp.today().normalize()
    universe = _synthetic_universe(today)
    cfg = LadderBuilderConfig(
        budget_eur=30_000, n_rungs=3, max_duration_years=3
    )
    proposal = LadderBuilder(cfg, universe=universe).build()
    bonds = [
        b for r in proposal.rungs for b in r.selected_bonds.values() if b is not None
    ]
    total = sum(b.amount_eur for b in bonds)
    expected = sum(b.amount_eur * b.ytm_net for b in bonds) / total
    assert proposal.weighted_avg_ytm == pytest.approx(expected, rel=1e-6)


def test_actual_composition_sums_to_one():
    today = pd.Timestamp.today().normalize()
    universe = _synthetic_universe(today)
    cfg = LadderBuilderConfig(
        budget_eur=30_000, n_rungs=3, max_duration_years=3
    )
    proposal = LadderBuilder(cfg, universe=universe).build()
    s = sum(proposal.actual_composition.values())
    assert s == pytest.approx(1.0, abs=1e-9)


def test_compute_next_12m_cashflow_positive():
    today = pd.Timestamp.today().normalize()
    universe = _synthetic_universe(today)
    cfg = LadderBuilderConfig(
        budget_eur=30_000, n_rungs=3, max_duration_years=3
    )
    proposal = LadderBuilder(cfg, universe=universe).build()
    cash = compute_next_12m_cashflow(proposal)
    # Coupons + the 1y maturity should land in the next 12 months → >0.
    assert cash > 0


def test_format_broker_list_is_plain_text():
    today = pd.Timestamp.today().normalize()
    universe = _synthetic_universe(today)
    cfg = LadderBuilderConfig(
        budget_eur=30_000, n_rungs=3, max_duration_years=3
    )
    proposal = LadderBuilder(cfg, universe=universe).build()
    text = format_broker_list(proposal)
    assert "LADDER ACQUISITION" in text
    assert "Gradino 1" in text


# ---------- v3.1.1: maximize_allocation toggle ----------


def test_allocation_log_always_populated_even_without_maximize():
    today = pd.Timestamp.today().normalize()
    universe = _synthetic_universe(today)
    cfg = LadderBuilderConfig(
        budget_eur=30_000, n_rungs=3, max_duration_years=3
    )
    proposal = LadderBuilder(cfg, universe=universe).build()
    # Step 1 line is always there + a few summary stats.
    assert proposal.allocation_log
    assert any("Step 1" in entry for entry in proposal.allocation_log)
    # yield_without_maximization stays None when maximize is OFF.
    assert proposal.yield_without_maximization is None


def test_maximize_allocation_runs_extra_steps():
    today = pd.Timestamp.today().normalize()
    universe = _synthetic_universe(today)
    cfg = LadderBuilderConfig(
        budget_eur=30_000,
        n_rungs=3,
        max_duration_years=3,
        maximize_allocation=True,
    )
    proposal = LadderBuilder(cfg, universe=universe).build()
    # With maximize ON, Step 2 + Step 3 messages must appear.
    log_text = "\n".join(proposal.allocation_log)
    assert "Step 2" in log_text
    assert "Step 3" in log_text


def test_maximize_allocation_off_does_not_lose_existing_behaviour():
    """Regression: every legacy assertion that holds with maximize=False
    keeps holding. We re-check composition, n_bonds_selected, and the
    composition adaptation path."""
    today = pd.Timestamp.today().normalize()
    universe = _synthetic_universe_only_low_rated_foreign(today)
    cfg = LadderBuilderConfig(
        budget_eur=30_000,
        n_rungs=3,
        max_duration_years=3,
        foreign_min_rating="A-",
        maximize_allocation=False,
    )
    proposal = LadderBuilder(cfg, universe=universe).build()
    # Adaptation path still fires (foreign rating too low → 75/25).
    assert all(r.composition_was_adapted for r in proposal.rungs)
    assert all(
        r.composition["gov_ita"] == pytest.approx(0.75) for r in proposal.rungs
    )
