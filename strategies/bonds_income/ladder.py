"""Bond Ladder management — composition, gaps, cash-flow projection, candidates.

This is NOT an algorithmic trading strategy. It provides decision support for
manually-managed bond ladders: tracks current positions, identifies maturity
buckets that are underweight against a target structure, projects cash flows
from coupons + maturities, and ranks screener candidates for filling gaps.

Design choices recorded with the user:
  - Default target: rolling 1-10y equal-weighted (10 buckets, 10% each).
  - 70% sovereign / 30% corporate.
  - Min rating for corporate: BBB- (investment grade only).
  - Liquidity reserve: 5% in cash or <1y bonds.
  - Max issuer concentration: 5% in any single corporate issuer.

Coupon-schedule assumption (for cash-flow projection): annual payment on
the anniversary of the coupon (approximated from maturity_date). When the
real coupon schedule becomes available (Phase 4 data feed), this becomes
the truth source and the assumption is dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from strategies.bonds_income.positions_io import (
    add_position,
    close_position,
    load_positions,
    update_position,
)

# Investment-grade ladder of S&P ratings, best -> worst within IG.
INVESTMENT_GRADE_RATINGS = [
    "AAA",
    "AA+",
    "AA",
    "AA-",
    "A+",
    "A",
    "A-",
    "BBB+",
    "BBB",
    "BBB-",
]


@dataclass
class LadderConfig:
    """Target ladder structure."""

    type: str = "rolling_equal_weight"
    maturity_buckets_years: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
    sovereign_weight: float = 0.70
    corporate_weight: float = 0.30
    min_rating_corporate: str = "BBB-"
    max_issuer_concentration_pct: float = 5.0
    liquidity_reserve_pct: float = 5.0

    def __post_init__(self) -> None:
        if abs(self.sovereign_weight + self.corporate_weight - 1.0) > 1e-6:
            raise ValueError("sovereign_weight + corporate_weight must equal 1.0")
        if self.min_rating_corporate not in INVESTMENT_GRADE_RATINGS:
            raise ValueError(f"min_rating_corporate must be IG, got {self.min_rating_corporate}")
        if not (0 <= self.liquidity_reserve_pct <= 50):
            raise ValueError("liquidity_reserve_pct must be in [0, 50]")

    def bucket_label(self, years_to_maturity: float) -> Optional[str]:
        """Return the bucket label for a given YTM, or None if out of range."""
        if years_to_maturity is None or pd.isna(years_to_maturity):
            return None
        y = float(years_to_maturity)
        if y < 0:
            return None
        buckets = list(self.maturity_buckets_years)
        # bucket "Ny" includes (N-1, N]
        for n in buckets:
            if y <= n:
                return f"{n}y"
        return f">{buckets[-1]}y"

    def all_bucket_labels(self) -> list[str]:
        return [f"{n}y" for n in self.maturity_buckets_years]

    def per_bucket_target_pct(self) -> float:
        return 100.0 / len(self.maturity_buckets_years)


class LadderTracker:
    """Read+modify the parquet ladder; analyse composition + gaps + cash flows."""

    def __init__(
        self,
        config: Optional[LadderConfig] = None,
        positions_path: Optional[str | Path] = None,
    ) -> None:
        self.config = config or LadderConfig()
        self.positions_path = Path(positions_path) if positions_path else None

    # -------- I/O passthroughs --------

    def reload(self) -> pd.DataFrame:
        return load_positions(self.positions_path)

    @property
    def positions(self) -> pd.DataFrame:
        return self.reload()

    @property
    def active(self) -> pd.DataFrame:
        df = self.positions
        return df[df["status"] == "active"] if "status" in df.columns else df

    def add_position(self, **kwargs) -> pd.DataFrame:
        return add_position(path=self.positions_path, **kwargs)

    def update_position(self, isin: str, **kwargs) -> pd.DataFrame:
        return update_position(isin, path=self.positions_path, **kwargs)

    def close_position(self, isin: str, **kwargs) -> pd.DataFrame:
        return close_position(isin, path=self.positions_path, **kwargs)

    # -------- composition --------

    def get_ladder_composition(self) -> pd.DataFrame:
        """One row per maturity bucket. Empty buckets are kept so the UI can
        show them as "needs filling"."""
        cfg = self.config
        df = self.active.copy()
        rows = []
        total_value = float(df["current_market_value_eur"].fillna(0).sum()) if not df.empty else 0.0
        for label in cfg.all_bucket_labels():
            # find positions whose bucket matches
            if df.empty:
                rows.append(
                    {
                        "maturity_bucket": label,
                        "n_positions": 0,
                        "total_value_eur": 0.0,
                        "sovereign_value_eur": 0.0,
                        "corporate_value_eur": 0.0,
                        "weighted_avg_ytm": float("nan"),
                        "current_pct": 0.0,
                        "target_pct": cfg.per_bucket_target_pct(),
                    }
                )
                continue
            mask = df["years_to_maturity"].apply(cfg.bucket_label) == label
            sub = df[mask]
            tv = float(sub["current_market_value_eur"].fillna(0).sum())
            sv = float(
                sub[sub["issuer_type"] == "Government"]["current_market_value_eur"].fillna(0).sum()
            )
            cv = float(
                sub[sub["issuer_type"] == "Corporate"]["current_market_value_eur"].fillna(0).sum()
            )
            if tv > 0 and "ytm_current" in sub.columns:
                weights = sub["current_market_value_eur"].fillna(0) / tv
                wavg = float((sub["ytm_current"].fillna(0) * weights).sum())
            else:
                wavg = float("nan")
            rows.append(
                {
                    "maturity_bucket": label,
                    "n_positions": int(len(sub)),
                    "total_value_eur": tv,
                    "sovereign_value_eur": sv,
                    "corporate_value_eur": cv,
                    "weighted_avg_ytm": wavg,
                    "current_pct": (tv / total_value * 100) if total_value > 0 else 0.0,
                    "target_pct": cfg.per_bucket_target_pct(),
                }
            )
        return pd.DataFrame(rows)

    # -------- gaps --------

    def get_gaps(self) -> list[dict]:
        """Identify buckets below target — return a list of actionable suggestions."""
        comp = self.get_ladder_composition()
        if comp.empty:
            return []
        total_value = float(comp["total_value_eur"].sum())
        # If the ladder has no positions yet, suggest filling EVERY bucket pro-rata
        # of the total bonds-sleeve target (caller-side). We expose this via a
        # special "empty" signal.
        gaps: list[dict] = []
        for _, row in comp.iterrows():
            bucket = row["maturity_bucket"]
            target_pct = float(row["target_pct"])
            current_pct = float(row["current_pct"])
            drift_pp = current_pct - target_pct
            target_value = total_value * target_pct / 100.0 if total_value > 0 else 0.0
            gap_eur = target_value - float(row["total_value_eur"])
            if gap_eur > total_value * 0.01:  # >1% of ladder
                gaps.append(
                    {
                        "bucket": bucket,
                        "target_pct": target_pct,
                        "current_pct": current_pct,
                        "drift_pp": drift_pp,
                        "gap_eur": round(gap_eur, 2),
                        "suggestion": (
                            f"Add ~€{gap_eur:,.0f} of {bucket} bond (target "
                            f"{target_pct:.1f}% vs current {current_pct:.1f}%)"
                        ),
                    }
                )
        return sorted(gaps, key=lambda g: -g["gap_eur"])

    # -------- cash flow projection --------

    def get_cash_flow_projection(
        self, *, horizon_weeks: int = 104, today: Optional[date] = None
    ) -> pd.DataFrame:
        """Projected cash flows from current ladder over the next N weeks.

        Coupon schedule: annual, anniversary of maturity_date. Coupon amount =
        face value × coupon% / 100. For more granular schedules (semi-annual
        for some corporates / US treasuries) we'd need real coupon-frequency
        data — flagged as Phase 4 TODO.

        Maturity: face value returned at maturity_date.

        Returns DataFrame: date, isin, description, type ('coupon'|'maturity'),
        amount_eur. Sorted by date.
        """
        today = today or date.today()
        end = today + timedelta(weeks=horizon_weeks)
        df = self.active
        rows: list[dict] = []
        if df.empty:
            return pd.DataFrame(columns=["date", "isin", "description", "type", "amount_eur"])

        for _, r in df.iterrows():
            mdate = r.get("maturity_date")
            if mdate is None or pd.isna(mdate):
                continue
            mdate = mdate if isinstance(mdate, date) else pd.to_datetime(mdate).date()
            quantity = float(r.get("quantity") or 0)
            face_total = quantity  # 1 unit == 1 EUR face (quantity holds EUR face)
            coupon_pct = float(r.get("coupon") or 0)
            annual_coupon_eur = face_total * coupon_pct / 100.0

            # Coupon payments: every Jan-N (anniversary of maturity_date) up to and
            # including the maturity year, but no later than maturity_date.
            if annual_coupon_eur > 0:
                year = today.year
                while True:
                    try:
                        cdate = date(year, mdate.month, mdate.day)
                    except ValueError:
                        # e.g. Feb 29 on a non-leap year — push to Feb 28
                        cdate = date(year, mdate.month, min(mdate.day, 28))
                    if cdate > end or cdate > mdate:
                        break
                    if cdate >= today:
                        rows.append(
                            {
                                "date": cdate,
                                "isin": r["isin"],
                                "description": r.get("description", ""),
                                "type": "coupon",
                                "amount_eur": round(annual_coupon_eur, 2),
                            }
                        )
                    year += 1

            # Maturity payment
            if today <= mdate <= end:
                rows.append(
                    {
                        "date": mdate,
                        "isin": r["isin"],
                        "description": r.get("description", ""),
                        "type": "maturity",
                        "amount_eur": round(face_total, 2),
                    }
                )

        cf = pd.DataFrame(rows)
        if cf.empty:
            return pd.DataFrame(columns=["date", "isin", "description", "type", "amount_eur"])
        return cf.sort_values("date").reset_index(drop=True)

    # -------- candidate suggestions --------

    def suggest_candidates_for_bucket(
        self,
        bucket: str,
        screener_df: pd.DataFrame,
        *,
        n_suggestions: int = 5,
        currency: str = "EUR",
    ) -> pd.DataFrame:
        """Given a bucket label like '5y' and a Bonds Screener DataFrame,
        rank top N candidates that would fit the gap.

        Ranking:
          1. years_to_maturity falls inside the bucket band
          2. exclude callable + inflation-linked (already filtered upstream, but
             enforced here as a safety net)
          3. corporate: rating >= min_rating_corporate (IG only); skip if missing
          4. currency matches
          5. issuer not already at concentration cap in the ladder
          6. sort by net_yield_pa desc, tie-break by years_to_maturity desc
        """
        cfg = self.config
        if screener_df is None or screener_df.empty:
            return pd.DataFrame()

        # Bucket interval
        labels = cfg.all_bucket_labels()
        if bucket not in labels:
            return pd.DataFrame()
        idx = labels.index(bucket)
        years_low = float(cfg.maturity_buckets_years[idx - 1]) if idx > 0 else 0.0
        years_high = float(cfg.maturity_buckets_years[idx])

        df = screener_df.copy()
        # Defensive filtering
        if "years_to_maturity" not in df.columns:
            return pd.DataFrame()
        mask = (df["years_to_maturity"] > years_low) & (df["years_to_maturity"] <= years_high)
        if "currency" in df.columns:
            mask &= df["currency"] == currency
        if "is_callable" in df.columns:
            mask &= ~df["is_callable"].fillna(False)
        if "inflation_linked" in df.columns:
            mask &= ~df["inflation_linked"].fillna(False)
        df = df[mask].copy()
        if df.empty:
            return df

        # Corporate rating gate
        if "issuer_type" in df.columns and "rating" in df.columns:
            is_corp = df["issuer_type"] == "Corporate"
            ig_set = set(
                INVESTMENT_GRADE_RATINGS[
                    : INVESTMENT_GRADE_RATINGS.index(cfg.min_rating_corporate) + 1
                ]
            )
            ok_corp = df["rating"].isin(ig_set)
            df = df[(~is_corp) | ok_corp]

        # Issuer concentration check
        active = self.active
        if not active.empty:
            issuer_values = (
                active.groupby("description")["current_market_value_eur"].sum()
                if "description" in active.columns
                else pd.Series(dtype=float)
            )
            total = active["current_market_value_eur"].sum()
            capped = set()
            if total > 0:
                cap = cfg.max_issuer_concentration_pct / 100.0 * total
                capped = set(issuer_values[issuer_values >= cap].index.tolist())
            if "description" in df.columns:
                df = df[~df["description"].isin(capped)]

        sort_cols = []
        sort_asc: list[bool] = []
        if "net_yield_pa" in df.columns:
            sort_cols.append("net_yield_pa")
            sort_asc.append(False)
        if "years_to_maturity" in df.columns:
            sort_cols.append("years_to_maturity")
            sort_asc.append(False)
        if sort_cols:
            df = df.sort_values(sort_cols, ascending=sort_asc)

        return df.head(n_suggestions)

    # -------- health check --------

    def health_check(self) -> dict:
        """Aggregate metrics + warnings — 0..100 score plus breakdown."""
        cfg = self.config
        df = self.active
        warnings: list[dict] = []
        score = 100.0

        if df.empty:
            return {
                "score": 0.0,
                "warnings": [{"level": "info", "message": "No positions on file."}],
                "metrics": {
                    "total_value_eur": 0.0,
                    "n_positions": 0,
                    "sovereign_pct": 0.0,
                    "corporate_pct": 0.0,
                    "weighted_avg_ytm": 0.0,
                    "weighted_avg_duration": 0.0,
                },
            }

        total_value = float(df["current_market_value_eur"].fillna(0).sum())
        sv = float(
            df[df["issuer_type"] == "Government"]["current_market_value_eur"].fillna(0).sum()
        )
        cv = float(df[df["issuer_type"] == "Corporate"]["current_market_value_eur"].fillna(0).sum())
        sov_pct = sv / total_value * 100 if total_value > 0 else 0.0
        cor_pct = cv / total_value * 100 if total_value > 0 else 0.0
        sov_drift = sov_pct - cfg.sovereign_weight * 100
        if abs(sov_drift) > 10:
            warnings.append(
                {
                    "level": "warning",
                    "message": f"sovereign/corporate mix off by {sov_drift:+.1f}pp "
                    f"(target {cfg.sovereign_weight * 100:.0f}/{cfg.corporate_weight * 100:.0f})",
                }
            )
            score -= min(20, abs(sov_drift))

        # Issuer concentration
        if "description" in df.columns:
            iss = df.groupby("description")["current_market_value_eur"].sum()
            if total_value > 0:
                cap = cfg.max_issuer_concentration_pct / 100.0 * total_value
                breaches = iss[iss > cap]
                for desc, v in breaches.items():
                    warnings.append(
                        {
                            "level": "warning",
                            "message": (
                                f"issuer concentration: {desc} = "
                                f"{v / total_value * 100:.1f}% > "
                                f"{cfg.max_issuer_concentration_pct:.0f}% cap"
                            ),
                        }
                    )
                    score -= 5

        # Rating gate (corporate)
        if {"issuer_type", "rating"}.issubset(df.columns):
            is_corp = df["issuer_type"] == "Corporate"
            ig_set = set(
                INVESTMENT_GRADE_RATINGS[
                    : INVESTMENT_GRADE_RATINGS.index(cfg.min_rating_corporate) + 1
                ]
            )
            below = df[is_corp & (~df["rating"].isin(ig_set)) & df["rating"].notna()]
            if not below.empty:
                warnings.append(
                    {
                        "level": "warning",
                        "message": f"{len(below)} corporate position(s) below "
                        f"{cfg.min_rating_corporate} minimum rating",
                    }
                )
                score -= 5 * len(below)

        # Liquidity reserve (<1y bonds + we have no live cash here, so just bonds)
        short = df[df["years_to_maturity"].fillna(0) < 1.0]
        short_pct = (
            float(short["current_market_value_eur"].fillna(0).sum()) / total_value * 100
            if total_value > 0
            else 0.0
        )
        if short_pct < cfg.liquidity_reserve_pct - 1:
            warnings.append(
                {
                    "level": "info",
                    "message": (
                        f"liquidity reserve at {short_pct:.1f}% "
                        f"(target {cfg.liquidity_reserve_pct:.0f}% in <1y bonds or cash)"
                    ),
                }
            )
            score -= min(10, cfg.liquidity_reserve_pct - short_pct)

        # YTM + duration metrics
        weights = (
            df["current_market_value_eur"].fillna(0) / total_value
            if total_value > 0
            else pd.Series(0.0, index=df.index)
        )
        wavg_ytm = (
            float((df["ytm_current"].fillna(0) * weights).sum())
            if "ytm_current" in df.columns
            else 0.0
        )
        wavg_dur = float((df["years_to_maturity"].fillna(0) * weights).sum())

        return {
            "score": max(0.0, round(score, 1)),
            "warnings": warnings,
            "metrics": {
                "total_value_eur": round(total_value, 2),
                "n_positions": int(len(df)),
                "sovereign_pct": round(sov_pct, 2),
                "corporate_pct": round(cor_pct, 2),
                "weighted_avg_ytm": round(wavg_ytm, 3),
                "weighted_avg_duration": round(wavg_dur, 2),
            },
        }
