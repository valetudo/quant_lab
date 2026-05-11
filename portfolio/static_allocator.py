"""Static Strategic Allocation — Phase 3 portfolio model.

Replaces the dynamic ``MasterAllocator`` from Phase 2. The decision recorded
with the user is:

  - Sleeve weights are FIXED targets (e.g. 60/30/10 bonds/equity/opportunistic).
  - No algorithmic rebalancing between sleeves. Drift > ``drift_threshold_pp``
    raises a UI alert; the user rebalances manually.
  - Each sleeve contains 1..N strategies that operate independently with
    that sleeve's capital budget.

The classes here are pure value objects + a thin ``StaticPortfolio``
container. The "current values" come from ``portfolio.state.PortfolioState``,
which knows how to read live positions and backtest outputs off disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable


@dataclass
class StrategicAllocation:
    """Fixed target weights across sleeves. Sleeve weights must sum to 1.0."""

    sleeve_targets: Dict[str, float]
    drift_threshold_pp: float = 5.0

    def __post_init__(self) -> None:
        total = sum(self.sleeve_targets.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Sleeve targets must sum to 1.0, got {total}")
        for sid, w in self.sleeve_targets.items():
            if w < 0:
                raise ValueError(f"Sleeve {sid} has negative weight {w}")


@dataclass
class SleeveDefinition:
    """One sleeve in the portfolio. ``strategy_weights`` must sum to 1.0
    unless the sleeve has no strategies (empty dict OK for placeholders
    like the opportunistic sleeve before any strategy is wired in)."""

    sleeve_id: str
    strategy_ids: list[str]
    strategy_weights: Dict[str, float]
    target_weight_of_total: float
    notes: str = ""

    def __post_init__(self) -> None:
        if not (0.0 <= self.target_weight_of_total <= 1.0):
            raise ValueError(
                f"sleeve {self.sleeve_id}: target_weight_of_total must be in [0,1], "
                f"got {self.target_weight_of_total}"
            )
        # Allow empty placeholder sleeves (no strategies yet).
        if self.strategy_weights:
            total = sum(self.strategy_weights.values())
            if abs(total - 1.0) > 1e-6:
                raise ValueError(
                    f"sleeve {self.sleeve_id}: strategy_weights sum to {total}, expected 1.0"
                )
            unknown = set(self.strategy_weights) - set(self.strategy_ids)
            if unknown:
                raise ValueError(
                    f"sleeve {self.sleeve_id}: strategy_weights references unknown "
                    f"strategies {sorted(unknown)}"
                )


class StaticPortfolio:
    """Multi-sleeve portfolio with static strategic weights.

    Drift is computed from a snapshot of current sleeve EUR values supplied by
    the caller. No algorithmic trading happens here — drift > threshold is a
    signal for the user (via the Portfolio Overview page) to rebalance manually.
    """

    def __init__(
        self,
        allocation: StrategicAllocation,
        sleeves: Iterable[SleeveDefinition],
        total_capital_eur: float,
    ) -> None:
        self.allocation = allocation
        self.sleeves: Dict[str, SleeveDefinition] = {s.sleeve_id: s for s in sleeves}
        self.total_capital_eur = float(total_capital_eur)

        for sid in self.allocation.sleeve_targets:
            if sid not in self.sleeves:
                raise ValueError(f"Sleeve {sid!r} listed in allocation but has no definition")
        for sid, defn in self.sleeves.items():
            t1 = self.allocation.sleeve_targets.get(sid)
            if t1 is None:
                raise ValueError(
                    f"Sleeve definition {sid!r} has no entry in allocation.sleeve_targets"
                )
            if abs(defn.target_weight_of_total - t1) > 1e-6:
                raise ValueError(
                    f"Sleeve {sid}: SleeveDefinition.target_weight_of_total "
                    f"({defn.target_weight_of_total}) doesn't match "
                    f"StrategicAllocation.sleeve_targets ({t1})"
                )

    # -------- capital helpers --------

    def get_sleeve_capital(self, sleeve_id: str) -> float:
        return self.total_capital_eur * self.allocation.sleeve_targets[sleeve_id]

    def get_strategy_capital(self, sleeve_id: str, strategy_id: str) -> float:
        sleeve = self.sleeves[sleeve_id]
        w = sleeve.strategy_weights.get(strategy_id)
        if w is None:
            raise KeyError(f"strategy {strategy_id!r} not in sleeve {sleeve_id!r}")
        return self.get_sleeve_capital(sleeve_id) * w

    # -------- drift analysis --------

    def compute_drift(self, current_sleeve_values_eur: Dict[str, float]) -> Dict[str, dict]:
        """Return drift analysis per sleeve.

        ``current_sleeve_values_eur`` maps sleeve_id -> live EUR value.
        Missing sleeves are treated as 0. The percentage drift is computed
        against the current grand total of all sleeves (so it stays
        meaningful when the portfolio grows/shrinks).
        """
        total_current = sum(float(v) for v in current_sleeve_values_eur.values())
        out: Dict[str, dict] = {}
        for sid, target_pct in self.allocation.sleeve_targets.items():
            current_value = float(current_sleeve_values_eur.get(sid, 0.0))
            current_pct = (current_value / total_current) if total_current > 0 else 0.0
            drift_pp = (current_pct - target_pct) * 100
            target_value = total_current * target_pct
            out[sid] = {
                "target_pct": target_pct * 100,
                "current_pct": current_pct * 100,
                "drift_pp": drift_pp,
                "alert": abs(drift_pp) > self.allocation.drift_threshold_pp,
                "current_value_eur": current_value,
                "target_value_eur": target_value,
                "delta_eur": current_value - target_value,
            }
        return out

    def rebalance_suggestions(self, current_sleeve_values_eur: Dict[str, float]) -> list[dict]:
        """Concrete suggestions for restoring target allocation manually.

        Returns a list of ``{from_sleeve, to_sleeve, amount_eur, reason}``
        actions sorted by absolute amount. The pairing is greedy: largest
        over-weight pays into largest under-weight until both reach target.
        """
        drift = self.compute_drift(current_sleeve_values_eur)
        # Only alerting sleeves participate; the others are within tolerance.
        donors = sorted(
            [
                (sid, d["delta_eur"])
                for sid, d in drift.items()
                if d["alert"] and d["delta_eur"] > 0
            ],
            key=lambda x: -x[1],
        )
        receivers = sorted(
            [
                (sid, -d["delta_eur"])
                for sid, d in drift.items()
                if d["alert"] and d["delta_eur"] < 0
            ],
            key=lambda x: -x[1],
        )
        suggestions: list[dict] = []
        di, ri = 0, 0
        while di < len(donors) and ri < len(receivers):
            d_sid, d_amt = donors[di]
            r_sid, r_amt = receivers[ri]
            move = min(d_amt, r_amt)
            if move > 0:
                suggestions.append(
                    {
                        "from_sleeve": d_sid,
                        "to_sleeve": r_sid,
                        "amount_eur": round(float(move), 2),
                        "reason": (
                            f"{d_sid} is +{drift[d_sid]['drift_pp']:.1f}pp, "
                            f"{r_sid} is {drift[r_sid]['drift_pp']:.1f}pp"
                        ),
                    }
                )
            donors[di] = (d_sid, d_amt - move)
            receivers[ri] = (r_sid, r_amt - move)
            if donors[di][1] <= 1e-6:
                di += 1
            if receivers[ri][1] <= 1e-6:
                ri += 1
        return suggestions
