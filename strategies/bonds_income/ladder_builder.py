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

    # ---- v3.1.1: "maximize allocation" strategy ----
    # When True, after the standard build pass, the builder applies up to
    # two fallback strategies to reach 100% allocation, accepting a small
    # yield hit:
    #
    #   (A) Tolerance window expansion: under-allocated rungs are re-built
    #       with ±12 / ±18 / ±24 months instead of the configured
    #       ``maturity_tolerance_months``.
    #   (B) Greedy reallocation: if more than ``min_residue_threshold_pct``
    #       of the budget is still unallocated, the residue is poured into
    #       the rungs with the best fill rate by adding extra lots of the
    #       cheapest already-picked bond.
    #
    # Default OFF — every legacy test exercises the standard pass only.
    maximize_allocation: bool = False
    max_tolerance_months: int = 24
    min_residue_threshold_pct: float = 5.0

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

    # ---- v3.1.1: maximize-allocation telemetry ----
    # Always populated, even when ``config.maximize_allocation`` is False.
    # Free-form lines the UI renders in an expander.
    allocation_log: list[str] = field(default_factory=list)
    # ``weighted_avg_ytm`` after the standard pass only — i.e. what the
    # proposal would have looked like without the maximization fallbacks.
    # ``None`` when maximization didn't run or didn't change anything.
    yield_without_maximization: Optional[float] = None

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
        """Standard pass, then (optionally) maximization fallbacks.

        Behavior when ``config.maximize_allocation`` is False — the v3.1.0
        default — is identical to the previous implementation: a single
        rung-by-rung pass over the universe. The proposal still gets a
        small ``allocation_log`` summarising the run, but no ``yield_without_maximization``.

        When the flag is True, the builder runs the standard pass first,
        then applies tolerance expansion + greedy reallocation as
        described in :class:`LadderBuilderConfig`.
        """
        proposal = self._build_standard()

        # Base log entries — always populated so the UI expander has content.
        proposal.allocation_log = [
            f"Step 1 (standard): allocato €{proposal.total_allocated_eur:,.0f} "
            f"/ €{proposal.total_target_eur:,.0f}",
            f"Bond selezionati: {proposal.n_bonds_selected}",
            f"Bond scartati: {proposal.n_bonds_skipped}",
            f"Gradini ribilanciati (gov estero → BTP): "
            f"{sum(1 for r in proposal.rungs if r.composition_was_adapted)}",
        ]

        if not self.config.maximize_allocation:
            return proposal

        # Track yield of the standard pass for the trade-off display.
        yield_step1 = proposal.weighted_avg_ytm

        # === Step A: tolerance window expansion for under-allocated rungs ===
        proposal.allocation_log.append(
            f"Step 2 (tolerance expansion): cerco bond extra per i gradini "
            f"sotto-allocati, finestra fino a ±{self.config.max_tolerance_months}m"
        )
        original_tol = self.config.maturity_tolerance_months
        # Use a sequence of expanded windows ending at the configured cap.
        expansion_steps: list[int] = []
        for tol in (12, 18, 24):
            if tol > original_tol and tol <= self.config.max_tolerance_months:
                expansion_steps.append(tol)
        universe = self._load_universe()

        for i, rung in enumerate(proposal.rungs):
            if rung.coverage_pct >= 0.9:
                continue
            for tol in expansion_steps:
                old_amount = rung.actual_amount_eur
                rebuilt = self._rebuild_rung_with_tolerance(
                    rung=rung,
                    tolerance_months=tol,
                    universe=universe,
                    proposal=proposal,
                )
                if rebuilt.actual_amount_eur > old_amount:
                    proposal.rungs[i] = rebuilt
                    proposal.allocation_log.append(
                        f"  Gradino {rung.rung_index + 1}: tolerance ±{tol}m → "
                        f"recuperati €{rebuilt.actual_amount_eur - old_amount:,.0f}"
                    )
                    rung = rebuilt
                    if rung.coverage_pct >= 0.9:
                        break

        # Restore the original tolerance setting on the config (we only
        # mutated it inside the helper, but defensive cleanup is cheap).
        self.config.maturity_tolerance_months = original_tol

        proposal.allocation_log.append(
            f"Step 2 done: allocato €{proposal.total_allocated_eur:,.0f}"
        )

        # === Step B: greedy reallocation of remaining residue ===
        residue = proposal.total_unallocated_eur
        residue_pct = (
            (residue / proposal.total_target_eur * 100)
            if proposal.total_target_eur > 0
            else 0
        )
        if residue_pct > self.config.min_residue_threshold_pct:
            proposal.allocation_log.append(
                f"Step 3 (greedy reallocation): residuo €{residue:,.0f} "
                f"({residue_pct:.1f}%) > soglia "
                f"{self.config.min_residue_threshold_pct:.0f}% — redistribuisco "
                f"sui gradini con miglior fill rate"
            )
            for _ in range(50):  # safety cap
                current_residue = proposal.total_unallocated_eur
                if current_residue < 100:  # less than €100 → stop
                    break
                target_rung = self._find_best_rung_for_reallocation(proposal)
                if target_rung is None:
                    proposal.allocation_log.append(
                        "  Greedy: nessun gradino con capacity, stop"
                    )
                    break
                added = self._add_extra_lot_to_rung(target_rung, current_residue)
                if added <= 0:
                    break
                proposal.allocation_log.append(
                    f"  Greedy: +€{added:,.0f} al gradino "
                    f"{target_rung.rung_index + 1}"
                )
            proposal.allocation_log.append(
                f"Step 3 done: allocato €{proposal.total_allocated_eur:,.0f}"
            )
        else:
            proposal.allocation_log.append(
                f"Step 3 saltato: residuo {residue_pct:.1f}% ≤ soglia "
                f"{self.config.min_residue_threshold_pct:.0f}%"
            )

        # Track the yield drift caused by maximization. Only attach when
        # it actually changed (otherwise the UI banner would lie).
        yield_now = proposal.weighted_avg_ytm
        if abs(yield_now - yield_step1) > 1e-6:
            proposal.yield_without_maximization = yield_step1

        return proposal

    # -------- standard pass (was the old build()) --------

    def _build_standard(self) -> LadderProposal:
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

    # -------- maximize-allocation helpers --------

    def _global_alloc_excluding_rung(
        self, proposal: LadderProposal, exclude_index: int
    ) -> dict[str, float]:
        """Issuer allocation across the proposal, minus the rung we're rebuilding.

        The concentration cap on corporate issuers must still be respected
        when re-attempting a rung. We rebuild the global_alloc dict from
        the current proposal state, skipping the rung whose bonds will be
        replaced.
        """
        alloc: dict[str, float] = {}
        for r in proposal.rungs:
            if r.rung_index == exclude_index:
                continue
            for bond in r.selected_bonds.values():
                if bond is not None:
                    alloc[bond.issuer] = alloc.get(bond.issuer, 0.0) + bond.amount_eur
        return alloc

    def _rebuild_rung_with_tolerance(
        self,
        *,
        rung: RungProposal,
        tolerance_months: int,
        universe: pd.DataFrame,
        proposal: LadderProposal,
    ) -> RungProposal:
        """Re-run ``_build_rung`` for one rung with a wider tolerance window.

        Mutates ``self.config.maturity_tolerance_months`` for the duration
        of the call, then restores it. The concentration cap is re-derived
        from the rest of the proposal so we don't double-count.
        """
        saved_tol = self.config.maturity_tolerance_months
        self.config.maturity_tolerance_months = tolerance_months
        try:
            global_alloc = self._global_alloc_excluding_rung(
                proposal, exclude_index=rung.rung_index
            )
            return self._build_rung(
                rung_index=rung.rung_index,
                target_maturity=rung.target_maturity_date,
                target_amount=rung.target_amount_eur,
                universe=universe,
                global_alloc=global_alloc,
            )
        finally:
            self.config.maturity_tolerance_months = saved_tol

    def _find_best_rung_for_reallocation(
        self, proposal: LadderProposal
    ) -> Optional[RungProposal]:
        """Pick a rung suitable for an extra lot: must have at least one
        selected bond (so we know the maturity window worked), and prefer
        the rung with the highest current coverage (least likely to bust
        the concentration cap, most likely to have headroom)."""
        candidates = [
            r for r in proposal.rungs if any(b is not None for b in r.selected_bonds.values())
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r.coverage_pct)

    def _add_extra_lot_to_rung(
        self, rung: RungProposal, available_amount: float
    ) -> float:
        """Add one more lot to the cheapest already-selected bond in this
        rung that fits inside ``available_amount`` and the concentration
        cap. Returns the euro amount added (0 if nothing fit).

        ``SelectedBond.quantity`` counts **lots**, not nominal EUR, so
        incrementing by 1 == one extra lot. ``amount_eur`` is recomputed
        consistently.
        """
        # Sort selected bonds in the rung by lot cost ascending, so we
        # add the cheapest first (maximises chance of fitting the residue).
        bonds = [
            b
            for b in rung.selected_bonds.values()
            if b is not None and b.price_clean > 0
        ]
        if not bonds:
            return 0.0
        bonds.sort(key=lambda b: b.lot_size_eur * b.price_clean / 100.0)
        for bond in bonds:
            lot_eur = bond.lot_size_eur * bond.price_clean / 100.0
            if lot_eur <= 0 or lot_eur > available_amount:
                continue
            # Concentration check (corp only).
            if bond.category == "corp":
                cap_eur = (
                    self.config.corp_max_issuer_concentration_pct
                    / 100.0
                    * self.config.budget_eur
                )
                # Rough self-derived current alloc for this issuer
                # (we don't have a proposal-wide alloc handy here; if the
                # extra lot would push us past the cap by more than 0.1pp,
                # skip it. The legacy concentration_warnings will still
                # flag the resulting overshoot for the UI.)
                existing = bond.amount_eur
                if existing + lot_eur > cap_eur * 1.001:
                    continue
            bond.quantity += 1
            bond.amount_eur += lot_eur
            return lot_eur
        return 0.0

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


# ---------- v3.1.2: optimal-params finder ----------


@dataclass
class ParamCandidate:
    """A point in the (n_rungs × max_duration) grid + its scoring metrics.

    The finder ranks candidates by ``coverage_pct`` (primary), then by
    ``weighted_avg_ytm`` (tiebreaker). The UI displays the top N.

    ``proposal`` carries the actual :class:`LadderProposal` the finder
    built when evaluating this combination. Stored as-is so the UI's
    "Usa questi" button can promote it to the live proposal without
    re-running the build (added in v3.1.4 — the visualisation flips
    instantly when the user clicks a different recommendation).
    Field is ``None`` only if a third-party caller constructs
    ``ParamCandidate`` manually for testing.
    """

    n_rungs: int
    max_duration_years: int
    coverage_pct: float  # 0..100
    weighted_avg_ytm: float  # decimal
    allocated_eur: float
    n_bonds_selected: int
    proposal: Optional["LadderProposal"] = None


# Reasonable defaults that cover the typical retail use cases (€10k–€500k,
# 1–30 year horizon). Skewed to "moderate" combinations — extreme corners
# (1 rung × 30 years, 30 rungs × 2 years) tend to score badly anyway.
_DEFAULT_RUNG_GRID: tuple[int, ...] = (3, 5, 7, 10, 12, 15)
_DEFAULT_DURATION_GRID: tuple[int, ...] = (5, 8, 10, 15, 20, 30)


def find_optimal_params(
    *,
    budget_eur: float,
    universe: Optional[pd.DataFrame] = None,
    bonds_db_path: Optional[Path | str] = None,
    base_config: Optional[LadderBuilderConfig] = None,
    rungs_grid: tuple[int, ...] = _DEFAULT_RUNG_GRID,
    duration_grid: tuple[int, ...] = _DEFAULT_DURATION_GRID,
    top_n: int = 5,
    min_coverage_pct: float = 80.0,
) -> list[ParamCandidate]:
    """Scan a grid of ``(n_rungs, max_duration_years)`` for ``budget_eur``
    and return the best ``top_n`` candidates by coverage (with YTM as
    tiebreaker).

    The universe can be passed pre-loaded (recommended — saves ~0.1 s in
    UI flows). When ``base_config`` is provided, all fields except
    ``budget_eur``, ``n_rungs`` and ``max_duration_years`` are inherited
    (so the user's "Impostazioni avanzate" still apply).

    Filter logic:
      1. Run every grid combination through ``LadderBuilder._build_standard``
         (NOT the full ``build`` — the maximize fallbacks are off-topic
         when comparing baseline configurations).
      2. Keep candidates that meet ``min_coverage_pct``.
      3. If none do, fall back to the top ``top_n`` regardless — the UI
         flags this case so the user knows the budget is constrained.
      4. Sort by (coverage desc, ytm desc) and take the top.
    """
    if universe is None:
        loader = BondsUniverseLoader(bonds_db_path)
        # Need a dummy config for the loader's currency / rating / etc.
        tmp_cfg = base_config or LadderBuilderConfig(budget_eur=budget_eur)
        universe = loader.load(tmp_cfg)

    candidates: list[ParamCandidate] = []
    for n_rungs in rungs_grid:
        for max_dur in duration_grid:
            # Skip ladder configurations that don't make physical sense
            # (more rungs than years — would crowd buckets too thin).
            if n_rungs > max_dur * 4:
                continue
            cfg = _clone_config(base_config, budget_eur, n_rungs, max_dur)
            try:
                builder = LadderBuilder(cfg, universe=universe)
                proposal = builder._build_standard()
            except Exception:
                # Bad config combination — skip it.
                continue
            coverage = (
                proposal.total_allocated_eur / proposal.total_target_eur * 100
                if proposal.total_target_eur > 0
                else 0.0
            )
            # Mirror the minimal allocation_log that build() would have
            # populated. Keeps the UI's "📋 Log dettagliato" expander
            # non-empty when the user promotes this proposal via "Usa questi".
            proposal.allocation_log = [
                f"Step 1 (standard): allocato €{proposal.total_allocated_eur:,.0f} "
                f"/ €{proposal.total_target_eur:,.0f}",
                f"Bond selezionati: {proposal.n_bonds_selected}",
                f"Bond scartati: {proposal.n_bonds_skipped}",
                f"Gradini ribilanciati (gov estero → BTP): "
                f"{sum(1 for r in proposal.rungs if r.composition_was_adapted)}",
                f"(generato da Trova parametri ottimali — n_rungs={n_rungs}, "
                f"max_duration={max_dur}y)",
            ]
            candidates.append(
                ParamCandidate(
                    n_rungs=n_rungs,
                    max_duration_years=max_dur,
                    coverage_pct=coverage,
                    weighted_avg_ytm=proposal.weighted_avg_ytm,
                    allocated_eur=proposal.total_allocated_eur,
                    n_bonds_selected=proposal.n_bonds_selected,
                    # Hold on to the actual proposal — the UI uses it to
                    # render the ladder immediately when the user clicks
                    # "Usa questi", without a second build pass.
                    proposal=proposal,
                )
            )

    if not candidates:
        return []

    above = [c for c in candidates if c.coverage_pct >= min_coverage_pct]
    pool = above if above else candidates
    pool.sort(key=lambda c: (-c.coverage_pct, -c.weighted_avg_ytm))
    return pool[:top_n]


def _clone_config(
    base: Optional[LadderBuilderConfig],
    budget_eur: float,
    n_rungs: int,
    max_duration_years: int,
) -> LadderBuilderConfig:
    """Make a new LadderBuilderConfig that inherits every advanced setting
    from ``base`` (if provided) but overrides the three "primary" knobs.
    """
    if base is None:
        return LadderBuilderConfig(
            budget_eur=budget_eur,
            n_rungs=n_rungs,
            max_duration_years=max_duration_years,
        )
    return LadderBuilderConfig(
        budget_eur=budget_eur,
        n_rungs=n_rungs,
        max_duration_years=max_duration_years,
        gov_ita_weight=base.gov_ita_weight,
        corp_weight=base.corp_weight,
        gov_foreign_weight=base.gov_foreign_weight,
        maturity_tolerance_months=base.maturity_tolerance_months,
        foreign_yield_must_exceed_btp=base.foreign_yield_must_exceed_btp,
        foreign_min_rating=base.foreign_min_rating,
        foreign_min_daily_volume_eur=base.foreign_min_daily_volume_eur,
        corp_min_rating=base.corp_min_rating,
        corp_exclude_subordinated=base.corp_exclude_subordinated,
        corp_exclude_callable_within_years=base.corp_exclude_callable_within_years,
        corp_max_issuer_concentration_pct=base.corp_max_issuer_concentration_pct,
        corp_currency=base.corp_currency,
        ranking_metric=base.ranking_metric,
        skip_if_lot_exceeds_budget=base.skip_if_lot_exceeds_budget,
        # Intentionally NOT inheriting maximize_allocation — the finder
        # always compares baselines (standard pass).
    )
