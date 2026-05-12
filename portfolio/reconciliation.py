"""Reconciliation between a broker snapshot and the unified PositionTracker.

The reconciliation diffs three sets keyed by ISIN:

- **new**       — present in the broker snapshot, absent from the tracker
- **updated**   — present in both, with different quantity and/or avg price
- **closed**    — present in the tracker, absent from the snapshot
- **unchanged** — present in both, equal within tolerance

The UI lets the user pick which deltas to apply; :func:`apply_deltas`
materialises the user's choices through the standard ``PositionTracker``
API (so the duplicate-ISIN guard and dual-write paths stay intact).

Broker-agnostic: the snapshot is a
:class:`core.data.importers.directa_xlsx.DirectaPortfolioSnapshot` today
but the pattern extends to any importer that produces objects with the
same shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from core.data.importers.directa_xlsx import (
    DirectaPortfolioSnapshot,
    DirectaPosition,
)
from portfolio.position_tracker import Position, PositionTracker


# Tolerance below which we treat ``quantity`` and ``avg_purchase_price``
# differences as noise (rounding / minor broker corrections).
_QTY_TOL = 0.01
_PRICE_TOL = 0.01


@dataclass
class ReconciliationDelta:
    """One row of the diff between snapshot and tracker."""

    delta_type: str  # "new" | "updated" | "closed" | "unchanged"
    isin: str
    name: str
    asset_class: str

    # Populated for "new" and "updated" deltas
    directa_position: Optional[DirectaPosition] = None

    # Populated for "updated" and "closed" deltas
    tracker_position: Optional[Position] = None

    # Computed for "updated" — the values to write through
    new_quantity: Optional[float] = None
    new_avg_price: Optional[float] = None


@dataclass
class ReconciliationReport:
    """The full diff between a snapshot and the live tracker state."""

    snapshot: DirectaPortfolioSnapshot
    deltas: list[ReconciliationDelta]

    @property
    def n_new(self) -> int:
        return sum(1 for d in self.deltas if d.delta_type == "new")

    @property
    def n_updated(self) -> int:
        return sum(1 for d in self.deltas if d.delta_type == "updated")

    @property
    def n_closed(self) -> int:
        return sum(1 for d in self.deltas if d.delta_type == "closed")

    @property
    def n_unchanged(self) -> int:
        return sum(1 for d in self.deltas if d.delta_type == "unchanged")

    def by_type(self, delta_type: str) -> list[ReconciliationDelta]:
        return [d for d in self.deltas if d.delta_type == delta_type]


def reconcile(
    snapshot: DirectaPortfolioSnapshot, tracker: PositionTracker
) -> ReconciliationReport:
    """Diff ``snapshot`` against the active rows in ``tracker``."""
    tracker_by_isin: dict[str, Position] = {
        p.isin: p for p in tracker.get_all() if p.status == "active"
    }
    snapshot_by_isin: dict[str, DirectaPosition] = {
        p.isin: p for p in snapshot.positions if p.isin
    }

    deltas: list[ReconciliationDelta] = []

    # NEW: in snapshot only
    for isin, sp in snapshot_by_isin.items():
        if isin in tracker_by_isin:
            continue
        deltas.append(
            ReconciliationDelta(
                delta_type="new",
                isin=isin,
                name=sp.name,
                asset_class=sp.asset_class,
                directa_position=sp,
            )
        )

    # CLOSED: in tracker only
    for isin, tp in tracker_by_isin.items():
        if isin in snapshot_by_isin:
            continue
        deltas.append(
            ReconciliationDelta(
                delta_type="closed",
                isin=isin,
                name=tp.name,
                asset_class=tp.asset_class,
                tracker_position=tp,
            )
        )

    # UPDATED / UNCHANGED: in both
    for isin in set(snapshot_by_isin) & set(tracker_by_isin):
        sp = snapshot_by_isin[isin]
        tp = tracker_by_isin[isin]
        qty_changed = abs((sp.quantity or 0) - (tp.quantity or 0)) > _QTY_TOL
        price_changed = (
            abs((sp.avg_purchase_price or 0) - (tp.avg_purchase_price or 0))
            > _PRICE_TOL
        )
        if qty_changed or price_changed:
            deltas.append(
                ReconciliationDelta(
                    delta_type="updated",
                    isin=isin,
                    name=tp.name,
                    asset_class=tp.asset_class,
                    directa_position=sp,
                    tracker_position=tp,
                    new_quantity=float(sp.quantity),
                    new_avg_price=float(sp.avg_purchase_price),
                )
            )
        else:
            deltas.append(
                ReconciliationDelta(
                    delta_type="unchanged",
                    isin=isin,
                    name=tp.name,
                    asset_class=tp.asset_class,
                    tracker_position=tp,
                )
            )

    return ReconciliationReport(snapshot=snapshot, deltas=deltas)


def apply_deltas(
    report: ReconciliationReport,
    tracker: PositionTracker,
    user_choices: dict[str, bool],
) -> dict[str, int]:
    """Apply only the deltas the user has confirmed.

    ``user_choices`` is a dict ``{isin: True (accept) | False (skip)}``.
    Returns a stats dict the UI can display::

        {"applied_new": ..., "applied_updated": ..., "applied_closed": ..., "skipped": ...}
    """
    stats = {"applied_new": 0, "applied_updated": 0, "applied_closed": 0, "skipped": 0}

    for delta in report.deltas:
        if delta.delta_type == "unchanged":
            continue
        if not user_choices.get(delta.isin, False):
            stats["skipped"] += 1
            continue

        try:
            if delta.delta_type == "new":
                dp = delta.directa_position
                if dp is None:
                    continue
                # Directa export doesn't carry a purchase date — use today.
                # Quantity convention: for bonds = nominal EUR (Directa
                # reports the same convention in its "Quantita" column);
                # for equities = number of shares.
                if delta.asset_class == "bond":
                    tracker.add_bond(
                        isin=dp.isin,
                        name=dp.name,
                        quantity=float(dp.quantity),
                        avg_purchase_price=float(dp.avg_purchase_price),
                        purchase_date=pd.Timestamp.today().normalize(),
                        issuer=dp.issuer,
                        notes=f"Imported from Directa on {pd.Timestamp.today().date()}",
                    )
                elif delta.asset_class == "equity":
                    tracker.add_equity(
                        isin=dp.isin,
                        name=dp.name,
                        quantity=float(dp.quantity),
                        avg_purchase_price=float(dp.avg_purchase_price),
                        purchase_date=pd.Timestamp.today().normalize(),
                        notes=f"Imported from Directa on {pd.Timestamp.today().date()}",
                    )
                else:
                    # "unknown" — skip; UI should warn the user separately.
                    stats["skipped"] += 1
                    continue
                stats["applied_new"] += 1

            elif delta.delta_type == "updated":
                tracker.update_position(
                    delta.isin,
                    quantity=delta.new_quantity,
                    avg_purchase_price=delta.new_avg_price,
                )
                stats["applied_updated"] += 1

            elif delta.delta_type == "closed":
                tracker.remove_position(delta.isin, reason="closed_per_directa")
                stats["applied_closed"] += 1
        except Exception:
            # If a single delta fails we count it as skipped and continue
            # (e.g. duplicate-ISIN guard fires when re-importing twice).
            stats["skipped"] += 1

    return stats
