"""Bond Ladder Builder.

Given a budget, a number of rungs, and a maximum duration, generate a
concrete bond purchase proposal that respects a per-rung composition
target (default 50% gov-ITA / 25% corporate-EUR / 25% gov-foreign-EUR).

The builder applies adaptive logic when the foreign sovereign slot fails
the triple quality filter (yield ≥ BTP equivalent, rating ≥ A-, liquidity
≥ €100k/day): the foreign weight collapses into gov-ITA, the rung
becomes 75/25 gov-ITA/corp. Skipped bonds are logged transparently so
the UI can show *why* a candidate was dropped.

This is **not** a trading algorithm — it produces a proposal a human then
executes manually at a retail broker. It is intentionally separated from
:class:`strategies.bonds_income.ladder.LadderTracker` (which tracks
positions already held).

Usage::

    from strategies.bonds_income.ladder_builder import (
        LadderBuilder, LadderBuilderConfig,
    )
    cfg = LadderBuilderConfig(budget_eur=50_000, n_rungs=10, max_duration_years=10)
    proposal = LadderBuilder(cfg).build()
    print(proposal.to_dataframe())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Literal, Optional

import pandas as pd

from core.data.bonds_universe import BondsUniverseLoader, rating_score


# ---------- config ----------


@dataclass
class LadderBuilderConfig:
    """User-configurable parameters for the ladder builder."""

    budget_eur: float
    n_rungs: int = 10
    max_duration_years: int = 10

    # Composition targets (must sum to 1.0)
    gov_ita_weight: float = 0.50
    corp_weight: float = 0.25
    gov_foreign_weight: float = 0.25

    # Maturity tolerance window per rung
    maturity_tolerance_months: int = 6

    # Foreign sovereign filters (ANY failing → redistribute to gov_ita)
    foreign_yield_must_exceed_btp: bool = True
    foreign_min_rating: str = "A-"
    foreign_min_daily_volume_eur: float = 100_000.0

    # Corporate filters
    corp_min_rating: str = "BBB-"
    corp_exclude_subordinated: bool = True
    corp_exclude_callable_within_years: int = 2
    corp_max_issuer_concentration_pct: float = 5.0
    corp_currency: str = "EUR"

    # Ranking metric
    ranking_metric: str = "yield_net"

    # Lot size handling
    skip_if_lot_exceeds_budget: bool = True

    def __post_init__(self) -> None:
        total = self.gov_ita_weight + self.corp_weight + self.gov_foreign_weight
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Composition weights must sum to 1.0, got {total:.4f} "
                f"(gov_ita={self.gov_ita_weight}, corp={self.corp_weight}, "
                f"gov_foreign={self.gov_foreign_weight})"
            )
        if self.budget_eur <= 0:
            raise ValueError(f"budget_eur must be > 0, got {self.budget_eur}")
        if self.n_rungs < 1:
            raise ValueError(f"n_rungs must be >= 1, got {self.n_rungs}")
        if self.max_duration_years < 1:
            raise ValueError(f"max_duration_years must be >= 1, got {self.max_duration_years}")


# ---------- result schema ----------


@dataclass
class SelectedBond:
    """A bond selected for inclusion in a rung."""

    isin: str
    name: str
    issuer: str
    category: Literal["gov_ita", "corp", "gov_foreign"]
    quantity: int  # number of lots
    lot_size_eur: float  # face value per lot (typically 1000)
    price_clean: float  # as % of face value
    amount_eur: float  # quantity * lot_size_eur * price_clean / 100
    ytm_net: float  # net YTM (decimal)
    coupon_rate: float  # annual coupon rate (decimal)
    coupon_frequency: int  # payments per year
    maturity_date: pd.Timestamp
    rating: Optional[str] = None
    country: Optional[str] = None

    def years_to_maturity(self, ref_date: Optional[pd.Timestamp] = None) -> float:
        ref = ref_date if ref_date is not None else pd.Timestamp.today().normalize()
        return (self.maturity_date - ref).days / 365.25


@dataclass
class SkippedBond:
    """A bond that was considered but excluded — kept for UI transparency."""

    isin: str
    name: str
    category: str
    reason: str
    details: str


@dataclass
class RungProposal:
    """Proposal for a single rung of the ladder."""

    rung_index: int  # 0-based
    target_maturity_date: pd.Timestamp
    tolerance_window: tuple[pd.Timestamp, pd.Timestamp]
    target_amount_eur: float
    composition: dict[str, float]  # effective composition after adaptive logic
    composition_was_adapted: bool = False
    adaptation_reason: Optional[str] = None
    selected_bonds: dict[str, Optional[SelectedBond]] = field(default_factory=dict)
    skipped_bonds: list[SkippedBond] = field(default_factory=list)

    @property
    def actual_amount_eur(self) -> float:
        return sum(b.amount_eur for b in self.selected_bonds.values() if b is not None)

    @property
    def coverage_pct(self) -> float:
        return self.actual_amount_eur / self.target_amount_eur if self.target_amount_eur > 0 else 0


@dataclass
class LadderProposal:
    """Full ladder proposal output."""

    config: LadderBuilderConfig
    generation_date: pd.Timestamp
    rungs: list[RungProposal]

    # ---- aggregates ----

    @property
    def total_target_eur(self) -> float:
        return self.config.budget_eur

    @property
    def total_allocated_eur(self) -> float:
        return sum(r.actual_amount_eur for r in self.rungs)

    @property
    def total_unallocated_eur(self) -> float:
        return self.total_target_eur - self.total_allocated_eur

    @property
    def n_bonds_selected(self) -> int:
        return sum(
            1 for r in self.rungs for b in r.selected_bonds.values() if b is not None
        )

    @property
    def n_bonds_skipped(self) -> int:
        return sum(len(r.skipped_bonds) for r in self.rungs)

    def _flat_selected(self) -> list[SelectedBond]:
        return [b for r in self.rungs for b in r.selected_bonds.values() if b is not None]

    @property
    def weighted_avg_ytm(self) -> float:
        bonds = self._flat_selected()
        total = sum(b.amount_eur for b in bonds)
        if total <= 0:
            return 0.0
        return sum(b.ytm_net * b.amount_eur for b in bonds) / total

    @property
    def weighted_avg_duration_years(self) -> float:
        bonds = self._flat_selected()
        total = sum(b.amount_eur for b in bonds)
        if total <= 0:
            return 0.0
        return sum(b.years_to_maturity() * b.amount_eur for b in bonds) / total

    @property
    def actual_composition(self) -> dict[str, float]:
        """Aggregate composition across all rungs as fraction of total allocated."""
        total = self.total_allocated_eur
        out = {"gov_ita": 0.0, "corp": 0.0, "gov_foreign": 0.0}
        if total <= 0:
            return out
        for r in self.rungs:
            for cat, bond in r.selected_bonds.items():
                if bond is not None and cat in out:
                    out[cat] += bond.amount_eur
        return {k: v / total for k, v in out.items()}

    @property
    def issuer_concentrations(self) -> dict[str, float]:
        total = self.total_allocated_eur
        if total <= 0:
            return {}
        agg: dict[str, float] = {}
        for r in self.rungs:
            for bond in r.selected_bonds.values():
                if bond is not None:
                    agg[bond.issuer] = agg.get(bond.issuer, 0.0) + bond.amount_eur
        return {iss: amt / total for iss, amt in agg.items()}

    @property
    def concentration_warnings(self) -> list[str]:
        cap = self.config.corp_max_issuer_concentration_pct / 100.0
        seen_warnings: set[str] = set()
        # Track corporate issuers only — gov_ita is intentionally concentrated.
        corp_alloc: dict[str, float] = {}
        for r in self.rungs:
            for bond in r.selected_bonds.values():
                if bond is not None and bond.category == "corp":
                    corp_alloc[bond.issuer] = corp_alloc.get(bond.issuer, 0.0) + bond.amount_eur
        total = self.total_allocated_eur or 1.0
        for issuer, amount in corp_alloc.items():
            conc = amount / total
            if conc > cap:
                seen_warnings.add(
                    f"{issuer}: {conc * 100:.1f}% > limite {cap * 100:.0f}%"
                )
        return sorted(seen_warnings)

    # ---- export helpers ----

    def to_dataframe(self) -> pd.DataFrame:
        """Flat one-row-per-bond table for UI display."""
        rows: list[dict] = []
        for rung in self.rungs:
            for category, bond in rung.selected_bonds.items():
                if bond is None:
                    continue
                rows.append(
                    {
                        "rung": rung.rung_index + 1,
                        "target_maturity": rung.target_maturity_date,
                        "category": category,
                        "isin": bond.isin,
                        "name": bond.name,
                        "issuer": bond.issuer,
                        "quantity": bond.quantity,
                        "price": bond.price_clean,
                        "amount_eur": bond.amount_eur,
                        "ytm_net": bond.ytm_net,
                        "maturity": bond.maturity_date,
                        "rating": bond.rating,
                    }
                )
        return pd.DataFrame(rows)


# ---------- builder ----------


class LadderBuilder:
    """Builds a :class:`LadderProposal` from a config and a bonds universe."""

    def __init__(
        self,
        config: LadderBuilderConfig,
        bonds_db_path: Optional[Path | str] = None,
        universe: Optional[pd.DataFrame] = None,
    ) -> None:
        self.config = config
        self.bonds_db_path = Path(bonds_db_path) if bonds_db_path else None
        self._universe_override = universe  # injectable for tests

    def build(self) -> LadderProposal:
        rung_targets = self._compute_rung_targets()
        amount_per_rung = self.config.budget_eur / self.config.n_rungs
        universe = self._load_universe()

        rungs: list[RungProposal] = []
        global_alloc: dict[str, float] = {}
        for i, target_date in enumerate(rung_targets):
            rung = self._build_rung(
                rung_index=i,
                target_maturity=target_date,
                target_amount=amount_per_rung,
                universe=universe,
                global_alloc=global_alloc,
            )
            rungs.append(rung)
            for bond in rung.selected_bonds.values():
                if bond is not None:
                    global_alloc[bond.issuer] = (
                        global_alloc.get(bond.issuer, 0.0) + bond.amount_eur
                    )

        return LadderProposal(
            config=self.config,
            generation_date=pd.Timestamp.today().normalize(),
            rungs=rungs,
        )

    # -------- internals --------

    def _compute_rung_targets(self) -> list[pd.Timestamp]:
        """Distribute rung maturities uniformly within [step .. max_duration]."""
        today = pd.Timestamp.today().normalize()
        if self.config.n_rungs == 1:
            return [
                today + pd.Timedelta(days=int(365.25 * self.config.max_duration_years))
            ]
        step = self.config.max_duration_years / self.config.n_rungs
        return [
            today + pd.Timedelta(days=int(365.25 * (i + 1) * step))
            for i in range(self.config.n_rungs)
        ]

    def _load_universe(self) -> pd.DataFrame:
        if self._universe_override is not None:
            return self._universe_override
        loader = BondsUniverseLoader(self.bonds_db_path)
        return loader.load(self.config)

    def _build_rung(
        self,
        rung_index: int,
        target_maturity: pd.Timestamp,
        target_amount: float,
        universe: pd.DataFrame,
        global_alloc: dict[str, float],
    ) -> RungProposal:
        tolerance_days = int(self.config.maturity_tolerance_months * 30.4375)
        window_start = target_maturity - timedelta(days=tolerance_days)
        window_end = target_maturity + timedelta(days=tolerance_days)

        in_window = universe[
            (universe["maturity_date"] >= window_start)
            & (universe["maturity_date"] <= window_end)
        ].copy()

        composition = {
            "gov_ita": self.config.gov_ita_weight,
            "corp": self.config.corp_weight,
            "gov_foreign": self.config.gov_foreign_weight,
        }
        skipped: list[SkippedBond] = []
        adapted = False
        adapt_reason: Optional[str] = None

        # === Foreign quality gate ===
        # If a candidate passes, the gate returns its row so the selection
        # step uses exactly that bond (and not a higher-yield one that
        # failed a filter).
        foreign_pre_selected: Optional[pd.Series] = None
        if self.config.gov_foreign_weight > 0:
            foreign_candidates = in_window[in_window["category"] == "gov_foreign"]
            gov_ita_window = in_window[in_window["category"] == "gov_ita"]
            btp_best_yield = (
                float(gov_ita_window["yield_net"].max())
                if not gov_ita_window.empty
                else 0.0
            )
            verdict = self._foreign_passes_quality(foreign_candidates, btp_best_yield)
            if not verdict["ok"]:
                adapted = True
                adapt_reason = verdict["reason"]
                composition = {
                    "gov_ita": self.config.gov_ita_weight + self.config.gov_foreign_weight,
                    "corp": self.config.corp_weight,
                    "gov_foreign": 0.0,
                }
                # Log the top-3 considered foreign candidates (transparency).
                for _, row in foreign_candidates.head(3).iterrows():
                    skipped.append(
                        SkippedBond(
                            isin=row.get("isin") or "UNK",
                            name=row.get("name") or "UNK",
                            category="gov_foreign",
                            reason=adapt_reason,
                            details=verdict.get("details", ""),
                        )
                    )
            else:
                foreign_pre_selected = verdict.get("candidate")

        # === Select within each non-zero category ===
        selected: dict[str, Optional[SelectedBond]] = {}
        for category, weight in composition.items():
            if weight <= 0:
                selected[category] = None
                continue
            category_target = target_amount * weight
            if category == "gov_foreign" and foreign_pre_selected is not None:
                # The gate already validated this exact row — use it.
                candidates = pd.DataFrame([foreign_pre_selected])
            else:
                candidates = in_window[in_window["category"] == category].copy()
                candidates = candidates[pd.notna(candidates["yield_net"])]
                candidates = candidates.sort_values("yield_net", ascending=False)
            chosen, cat_skipped = self._select_best_in_category(
                category=category,
                target_amount=category_target,
                candidates=candidates,
                global_alloc=global_alloc,
            )
            selected[category] = chosen
            skipped.extend(cat_skipped)

        return RungProposal(
            rung_index=rung_index,
            target_maturity_date=target_maturity,
            tolerance_window=(window_start, window_end),
            target_amount_eur=target_amount,
            composition=composition,
            composition_was_adapted=adapted,
            adaptation_reason=adapt_reason,
            selected_bonds=selected,
            skipped_bonds=skipped,
        )

    def _foreign_passes_quality(
        self, foreign_candidates: pd.DataFrame, btp_best_yield: float
    ) -> dict:
        """Find the highest-yield foreign candidate that satisfies all three
        quality filters. Returns ``{"ok": True}`` if at least one passes,
        else ``{"ok": False, "reason": ..., "details": ...}`` describing
        why the best (top-yield) candidate failed.

        Note vs. the literal spec ("best foreign by yield must pass"): we
        iterate down the yield ranking instead of one-shot rejecting. This
        is more useful in practice — a higher-yield BBB- foreign should
        not lock out a slightly-lower-yield AAA German Bund.
        """
        ranked = foreign_candidates.dropna(subset=["yield_net"]).sort_values(
            "yield_net", ascending=False
        )
        if ranked.empty:
            return {
                "ok": False,
                "reason": "no_eligible_foreign",
                "details": "Nessun gov estero in finestra di scadenza",
            }

        min_score = rating_score(self.config.foreign_min_rating)
        vol_col = "daily_volume_30d_avg"

        first_failure: Optional[dict] = None
        for _, row in ranked.iterrows():
            # Filter 1: yield ≥ best BTP yield
            row_yield = float(row.get("yield_net") or 0)
            if self.config.foreign_yield_must_exceed_btp and row_yield < btp_best_yield:
                if first_failure is None:
                    first_failure = {
                        "ok": False,
                        "reason": "foreign_yield_below_btp",
                        "details": (
                            f"Yield estero {row_yield * 100:.2f}% < "
                            f"BTP {btp_best_yield * 100:.2f}%"
                        ),
                    }
                continue
            # Filter 2: rating ≥ min
            row_score = int(row.get("rating_score") or 99)
            if row_score > min_score:
                if first_failure is None:
                    first_failure = {
                        "ok": False,
                        "reason": "foreign_rating_too_low",
                        "details": (
                            f"Rating {row.get('rating') or 'NR'} "
                            f"< {self.config.foreign_min_rating}"
                        ),
                    }
                continue
            # Filter 3: liquidity (if column available)
            if vol_col in foreign_candidates.columns:
                vol = float(row.get(vol_col) or 0)
                if vol < self.config.foreign_min_daily_volume_eur:
                    if first_failure is None:
                        first_failure = {
                            "ok": False,
                            "reason": "foreign_low_liquidity",
                            "details": (
                                f"Volume €{vol:,.0f} < "
                                f"€{self.config.foreign_min_daily_volume_eur:,.0f}"
                            ),
                        }
                    continue
            # Passed all filters — caller will use exactly this row.
            return {"ok": True, "candidate": row}

        # No candidate passed.
        return first_failure or {
            "ok": False,
            "reason": "no_eligible_foreign",
            "details": "Nessun gov estero supera i filtri di qualità",
        }

    def _select_best_in_category(
        self,
        category: str,
        target_amount: float,
        candidates: pd.DataFrame,
        global_alloc: dict[str, float],
    ) -> tuple[Optional[SelectedBond], list[SkippedBond]]:
        """Pick the first candidate in yield-descending order that fits
        ``target_amount`` and the concentration cap. Returns the chosen
        bond (or None) plus the list of skipped candidates above it.
        """
        skipped: list[SkippedBond] = []
        concentration_cap_eur = (
            self.config.corp_max_issuer_concentration_pct / 100.0 * self.config.budget_eur
        )

        # Per-category min rating check (gov_ita is unfiltered: sovereign IT
        # is the benchmark by definition; corp rating already pre-filtered
        # in the universe loader for corp_min_rating).
        if category == "corp":
            min_score = rating_score(self.config.corp_min_rating)
            ok = candidates["rating_score"].fillna(99) <= min_score
            for _, row in candidates[~ok].iterrows():
                skipped.append(
                    SkippedBond(
                        isin=row.get("isin") or "UNK",
                        name=row.get("name") or "UNK",
                        category=category,
                        reason="corp_rating_too_low",
                        details=(
                            f"Rating {row.get('rating') or 'NR'} < "
                            f"{self.config.corp_min_rating}"
                        ),
                    )
                )
            candidates = candidates[ok]

        for _, row in candidates.iterrows():
            lot_size_eur = float(row.get("lot_size_eur") or 1000.0)
            price = float(row.get("price_clean") or 100.0)
            if price <= 0:
                continue
            price_per_lot_eur = lot_size_eur * price / 100.0
            max_lots = int(target_amount // price_per_lot_eur)
            if max_lots < 1:
                if self.config.skip_if_lot_exceeds_budget:
                    skipped.append(
                        SkippedBond(
                            isin=row.get("isin") or "UNK",
                            name=row.get("name") or "UNK",
                            category=category,
                            reason="lot_size_exceeds_budget",
                            details=(
                                f"Lotto €{price_per_lot_eur:,.0f} > "
                                f"budget gradino €{target_amount:,.0f}"
                            ),
                        )
                    )
                    continue

            # Corporate concentration cap (gov_ita / gov_foreign concentrate
            # by design on a single sovereign — no cap there).
            if category == "corp":
                issuer = str(row.get("issuer") or "UNK")
                current = global_alloc.get(issuer, 0.0)
                this_amount = max_lots * price_per_lot_eur
                if current + this_amount > concentration_cap_eur:
                    # Try to scale down to fit the cap.
                    headroom = concentration_cap_eur - current
                    if headroom < price_per_lot_eur:
                        skipped.append(
                            SkippedBond(
                                isin=row.get("isin") or "UNK",
                                name=row.get("name") or "UNK",
                                category=category,
                                reason="concentration_limit",
                                details=(
                                    f"{issuer}: già €{current:,.0f} + "
                                    f"€{this_amount:,.0f} > cap "
                                    f"€{concentration_cap_eur:,.0f}"
                                ),
                            )
                        )
                        continue
                    max_lots = int(headroom // price_per_lot_eur)

            amount_eur = max_lots * price_per_lot_eur
            maturity = pd.to_datetime(row.get("maturity_date"))
            return (
                SelectedBond(
                    isin=str(row.get("isin") or "UNK"),
                    name=str(row.get("name") or "UNK"),
                    issuer=str(row.get("issuer") or "UNK"),
                    category=category,  # type: ignore[arg-type]
                    quantity=max_lots,
                    lot_size_eur=lot_size_eur,
                    price_clean=price,
                    amount_eur=amount_eur,
                    ytm_net=float(row.get("yield_net") or 0.0),
                    coupon_rate=float(row.get("coupon_rate") or 0.0),
                    coupon_frequency=int(row.get("coupon_frequency") or 1),
                    maturity_date=maturity,
                    rating=row.get("rating"),
                    country=row.get("nation"),
                ),
                skipped,
            )

        return None, skipped


# ---------- helpers consumed by the UI ----------


def compute_next_12m_cashflow(proposal: LadderProposal) -> float:
    """Total expected cash (coupons + maturities) in the next 12 months."""
    today = pd.Timestamp.today().normalize()
    cutoff = today + pd.DateOffset(months=12)
    total = 0.0
    for rung in proposal.rungs:
        for bond in rung.selected_bonds.values():
            if bond is None:
                continue
            face_total = bond.quantity * bond.lot_size_eur
            if bond.coupon_frequency <= 0:
                continue
            coupon_payment = face_total * bond.coupon_rate / bond.coupon_frequency
            # Walk coupon dates backwards from maturity.
            current = bond.maturity_date
            step = pd.DateOffset(months=int(12 // bond.coupon_frequency))
            seen = 0
            while current > today and seen < 60:
                if today < current <= cutoff:
                    total += coupon_payment
                current = current - step
                seen += 1
            # Maturity event (capital repayment — coupon already counted).
            if today < bond.maturity_date <= cutoff:
                total += face_total
    return total


def format_broker_list(proposal: LadderProposal) -> str:
    """Plain-text purchase list ready to copy into a broker order screen."""
    lines = [
        f"LADDER ACQUISITION — {proposal.generation_date.strftime('%Y-%m-%d')}",
        f"Budget: €{proposal.total_target_eur:,.2f}",
        f"Allocato: €{proposal.total_allocated_eur:,.2f} "
        f"({proposal.n_bonds_selected} bond)",
        "",
    ]
    for rung in proposal.rungs:
        lines.append(
            f"[Gradino {rung.rung_index + 1} — "
            f"target {rung.target_maturity_date.strftime('%Y-%m')}]"
        )
        for category, bond in rung.selected_bonds.items():
            if bond is None:
                lines.append(f"  ⊗ Skipped: {category}")
                continue
            lines.append(
                f"  ✓ {bond.name}  →  ISIN {bond.isin}  →  "
                f"{bond.quantity} lotti @ {bond.price_clean:.2f}  =  "
                f"€{bond.amount_eur:,.0f}"
            )
        lines.append("")
    lines.append(
        f"Totale: {proposal.n_bonds_selected} bond, "
        f"€{proposal.total_allocated_eur:,.0f} "
        f"({proposal.total_unallocated_eur:,.0f}€ non allocati)"
    )
    return "\n".join(lines)
