"""Unified Position Tracker for all asset classes.

Single source of truth for "what do I own right now". One parquet file
keyed by asset_class:

    data_storage/positions/portfolio_positions.parquet

Bond-specific columns (issuer, maturity_date, coupon_rate, …) are stored
on the same row as a Position with ``asset_class == "bond"``; equity rows
leave those NaN. The existing :class:`strategies.bonds_income.ladder.LadderTracker`
continues to use its own ``data_storage/bonds/positions.parquet`` for the
detail-rich bond view (composition, gaps, cash-flow projection); it is
fed by a dual-write helper so the two stores stay in sync.

New non-bond positions (equity ETFs, alternative-strategy stakes) only
go into this unified store.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal, Optional

import pandas as pd

log = logging.getLogger(__name__)


AssetClass = Literal["bond", "equity", "alternative", "cash"]


@dataclass
class Position:
    """A single position in the portfolio."""

    # Identifiers
    isin: str
    name: str
    asset_class: AssetClass

    # Quantity & price (units vary by asset_class)
    quantity: float  # bonds: nominal EUR; ETFs: shares; alternative: 1
    avg_purchase_price: float  # bonds: % of face; ETFs: EUR/share; alt: EUR total
    purchase_date: pd.Timestamp

    # Bond-only fields (None for non-bond)
    issuer: Optional[str] = None
    maturity_date: Optional[pd.Timestamp] = None
    coupon_rate: Optional[float] = None
    coupon_frequency: Optional[int] = None
    ytm_at_purchase: Optional[float] = None
    rating: Optional[str] = None

    # Cross-cutting
    sleeve: Optional[str] = None
    strategy_id: Optional[str] = None  # alternative only
    notes: Optional[str] = None
    status: str = "active"  # active | matured | sold
    last_updated: pd.Timestamp = field(default_factory=pd.Timestamp.now)

    def to_dict(self) -> dict:
        d = asdict(self)
        for k, v in list(d.items()):
            if isinstance(v, pd.Timestamp):
                d[k] = v.isoformat()
            elif v is pd.NaT:
                d[k] = None
        return d


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


class PositionTracker:
    """Unified tracker for all portfolio positions."""

    def __init__(self, positions_path: Optional[Path | str] = None) -> None:
        if positions_path:
            self.positions_path = Path(positions_path)
        else:
            self.positions_path = (
                _repo_root() / "data_storage" / "positions" / "portfolio_positions.parquet"
            )
        self.positions_path.parent.mkdir(parents=True, exist_ok=True)
        self._positions: list[Position] = []
        self._load()

    # ---------- persistence ----------

    def _load(self) -> None:
        if not self.positions_path.exists():
            self._positions = []
            return
        try:
            df = pd.read_parquet(self.positions_path)
        except Exception as e:
            log.warning("PositionTracker._load: %s", e)
            self._positions = []
            return
        self._positions = [self._row_to_position(row) for _, row in df.iterrows()]

    def _row_to_position(self, row: pd.Series) -> Position:
        kwargs: dict = {}
        for f_name, _ in Position.__dataclass_fields__.items():
            if f_name not in row.index:
                continue
            val = row[f_name]
            if isinstance(val, float) and pd.isna(val):
                val = None
            elif val is pd.NaT:
                val = None
            kwargs[f_name] = val
        # Coerce timestamps
        for ts_field in ("purchase_date", "maturity_date", "last_updated"):
            v = kwargs.get(ts_field)
            if v is not None and not isinstance(v, pd.Timestamp):
                try:
                    kwargs[ts_field] = pd.Timestamp(v)
                except Exception:
                    kwargs[ts_field] = None
        if kwargs.get("last_updated") is None:
            kwargs["last_updated"] = pd.Timestamp.now()
        # Drop unknown keys
        valid = {k for k in Position.__dataclass_fields__}
        kwargs = {k: v for k, v in kwargs.items() if k in valid}
        return Position(**kwargs)

    def save(self) -> None:
        if self.positions_path.exists():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = self.positions_path.parent / f"positions_backup_{ts}.parquet"
            try:
                shutil.copy(self.positions_path, backup)
            except Exception as e:
                log.warning("PositionTracker.save backup failed: %s", e)
        rows = [p.to_dict() for p in self._positions]
        df = pd.DataFrame(rows)
        df.to_parquet(self.positions_path, index=False)

    # ---------- mutators ----------

    def _active_isins(self) -> set[str]:
        return {p.isin for p in self._positions if p.status == "active"}

    def add_position(self, position: Position, *, allow_duplicate: bool = False) -> None:
        """Append a new position. Raises ``ValueError`` if an active row
        with the same ISIN already exists (set ``allow_duplicate=True`` to
        bypass — only intended for test fixtures).
        """
        if not allow_duplicate and position.isin in self._active_isins():
            raise ValueError(
                f"ISIN {position.isin!r} is already an active position. "
                f"Rimuovi la riga esistente prima di re-inserirla, oppure "
                f"usa il bottone 'Modifica' su Aggiorna Posizioni."
            )
        self._positions.append(position)
        self.save()

    def add_bond(
        self,
        *,
        isin: str,
        name: str,
        quantity: float,
        avg_purchase_price: float,
        purchase_date,
        issuer: Optional[str] = None,
        maturity_date=None,
        coupon_rate: Optional[float] = None,
        coupon_frequency: Optional[int] = 1,
        ytm_at_purchase: Optional[float] = None,
        rating: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> None:
        pos = Position(
            isin=isin,
            name=name,
            asset_class="bond",
            quantity=float(quantity),
            avg_purchase_price=float(avg_purchase_price),
            purchase_date=pd.Timestamp(purchase_date),
            issuer=issuer,
            maturity_date=(pd.Timestamp(maturity_date) if maturity_date else None),
            coupon_rate=coupon_rate,
            coupon_frequency=coupon_frequency,
            ytm_at_purchase=ytm_at_purchase,
            rating=rating,
            sleeve="bonds",
            notes=notes,
        )
        self.add_position(pos)

    def add_equity(
        self,
        *,
        isin: str,
        name: str,
        quantity: float,
        avg_purchase_price: float,
        purchase_date,
        notes: Optional[str] = None,
    ) -> None:
        pos = Position(
            isin=isin,
            name=name,
            asset_class="equity",
            quantity=float(quantity),
            avg_purchase_price=float(avg_purchase_price),
            purchase_date=pd.Timestamp(purchase_date),
            sleeve="equity",
            notes=notes,
        )
        self.add_position(pos)

    def add_alternative(
        self,
        *,
        strategy_id: str,
        name: str,
        quantity: float,
        avg_purchase_price: float,
        purchase_date,
        notes: Optional[str] = None,
    ) -> None:
        # ISIN for alternative positions doesn't exist — use the strategy
        # id namespaced + date so it's unique within the parquet.
        pseudo_isin = f"ALT-{strategy_id}-{pd.Timestamp(purchase_date).strftime('%Y%m%d')}"
        pos = Position(
            isin=pseudo_isin,
            name=name,
            asset_class="alternative",
            quantity=float(quantity),
            avg_purchase_price=float(avg_purchase_price),
            purchase_date=pd.Timestamp(purchase_date),
            sleeve="alternative",
            strategy_id=strategy_id,
            notes=notes,
        )
        self.add_position(pos)

    def remove_position(self, isin: str, reason: str = "sold") -> None:
        for p in self._positions:
            if p.isin == isin and p.status == "active":
                p.status = reason
                p.last_updated = pd.Timestamp.now()
        self.save()

    def update_position(self, isin: str, **updates) -> None:
        for p in self._positions:
            if p.isin == isin and p.status == "active":
                for k, v in updates.items():
                    if hasattr(p, k):
                        setattr(p, k, v)
                p.last_updated = pd.Timestamp.now()
        self.save()

    # ---------- queries ----------

    def get_all(self, status: str = "active") -> list[Position]:
        return [p for p in self._positions if p.status == status]

    def get_by_asset_class(self, asset_class: AssetClass) -> list[Position]:
        return [
            p for p in self._positions
            if p.asset_class == asset_class and p.status == "active"
        ]

    def get_by_sleeve(self, sleeve: str) -> list[Position]:
        return [p for p in self._positions if p.sleeve == sleeve and p.status == "active"]

    def to_dataframe(self, status: str = "active") -> pd.DataFrame:
        rows = [p.to_dict() for p in self._positions if p.status == status]
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    # ---------- valuation ----------

    def current_value_eur(self, current_prices: dict[str, float]) -> dict[str, float]:
        """Compute current value per asset class.

        ``current_prices`` is keyed by ISIN. Falls back to the average
        purchase price when a price is missing — i.e. shows "cost basis"
        for un-priced positions, which is safe for portfolio totals.
        """
        out = {"bond": 0.0, "equity": 0.0, "alternative": 0.0, "cash": 0.0}
        for p in self.get_all():
            current_price = current_prices.get(p.isin)
            if current_price is None or (isinstance(current_price, float) and pd.isna(current_price)):
                current_price = p.avg_purchase_price
            if p.asset_class == "bond":
                value = p.quantity * current_price / 100.0
            elif p.asset_class == "alternative":
                # alternatives store "amount EUR" in avg_purchase_price; no
                # mark-to-market — value = capital deployed.
                value = p.avg_purchase_price * p.quantity
            else:
                value = p.quantity * current_price
            out[p.asset_class] = out.get(p.asset_class, 0.0) + value
        out["total"] = sum(v for k, v in out.items() if k != "total")
        return out

    def unrealized_pnl(self, current_prices: dict[str, float]) -> pd.DataFrame:
        rows: list[dict] = []
        for p in self.get_all():
            current_price = current_prices.get(p.isin)
            price_missing = current_price is None or (
                isinstance(current_price, float) and pd.isna(current_price)
            )
            if price_missing:
                current_price = p.avg_purchase_price
            if p.asset_class == "bond":
                cost_basis = p.quantity * p.avg_purchase_price / 100.0
                current_value = p.quantity * current_price / 100.0
            elif p.asset_class == "alternative":
                cost_basis = p.avg_purchase_price * p.quantity
                current_value = cost_basis
            else:
                cost_basis = p.quantity * p.avg_purchase_price
                current_value = p.quantity * current_price
            pnl_eur = current_value - cost_basis
            pnl_pct = (pnl_eur / cost_basis * 100.0) if cost_basis > 0 else 0.0
            rows.append(
                {
                    "isin": p.isin,
                    "name": p.name,
                    "asset_class": p.asset_class,
                    "quantity": p.quantity,
                    "avg_purchase_price": p.avg_purchase_price,
                    "current_price": current_price,
                    "price_is_stale": price_missing,
                    "cost_basis_eur": cost_basis,
                    "current_value_eur": current_value,
                    "pnl_eur": pnl_eur,
                    "pnl_pct": pnl_pct,
                    "purchase_date": p.purchase_date,
                    "sleeve": p.sleeve,
                }
            )
        return pd.DataFrame(rows)
