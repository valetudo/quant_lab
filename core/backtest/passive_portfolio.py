"""Multi-asset passive portfolio backtester (buy & hold + periodic rebalance).

NOT a strategy in the engine sense — no signal generation, no costs model
plumbed into the engine, no per-bar event loop. Just:

1. Pull adj_close for each symbol over [start, end].
2. Identify "existence" per symbol at each date (handles ETFs that listed
   mid-window, e.g. XLC from 2018, XLRE from 2015 — their weight is
   renormalised across the other symbols available that day).
3. Buy at the first bar with the target weights (renormalised over the
   symbols available that day).
4. Hold (or, if ``rebalancing`` is set, rebalance to target weights on the
   first trading day of the rebalance period).
5. Mark to market daily; report equity series + the usual metrics.

Slippage is modelled as a flat bps haircut on each leg sold + bought at
each rebalance (default 5 bps each way). Buy-and-hold ("none") portfolios
pay no slippage at all beyond the initial entry — but since "EUR 100k →
shares" is identical in every scenario, we only charge slippage at
rebalances. That keeps the comparison apples-to-apples.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Optional

import pandas as pd

from core.data.storage import DataStorage, load_global_config


@dataclass
class PassivePortfolioResult:
    name: str
    weights: Dict[str, float]
    rebalancing: str
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    initial_capital_eur: float
    final_equity_eur: float
    daily_equity: pd.Series
    annual_returns: pd.DataFrame  # cols: year, return_pct
    holdings_history: pd.DataFrame  # date index, one column per symbol (EUR value)
    rebalance_events: pd.DataFrame  # cols: date, total_slippage_eur
    cagr: float
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown: float  # negative decimal
    max_dd_peak: Optional[pd.Timestamp] = None
    max_dd_trough: Optional[pd.Timestamp] = None
    annualized_vol: float = 0.0
    total_return_pct: float = 0.0
    total_slippage_cost_eur: float = 0.0
    renormalisation_days: int = 0  # how many days at least one symbol was missing
    notes: list[str] = field(default_factory=list)


def _is_rebalance_day(d: pd.Timestamp, prev_d: Optional[pd.Timestamp], freq: str) -> bool:
    if prev_d is None:
        return False
    if freq == "monthly":
        return d.month != prev_d.month
    if freq == "quarterly":
        # quarterly = first trading day of Jan / Apr / Jul / Oct
        return d.month != prev_d.month and d.month in (1, 4, 7, 10)
    if freq == "yearly":
        return d.year != prev_d.year
    return False


class PassivePortfolio:
    """Multi-symbol buy & hold (+ optional periodic rebalance)."""

    def __init__(
        self,
        name: str,
        weights: Dict[str, float],
        *,
        rebalancing: str = "quarterly",
        storage: Optional[DataStorage] = None,
        slippage_bps_per_leg: float = 5.0,
    ) -> None:
        s = float(sum(weights.values()))
        if abs(s - 1.0) > 1e-6:
            raise ValueError(f"weights for {name!r} must sum to 1.0; got {s}")
        for k, v in weights.items():
            if v < 0:
                raise ValueError(f"{name!r}: negative weight for {k}: {v}")
        if rebalancing not in ("none", "monthly", "quarterly", "yearly"):
            raise ValueError(f"{name!r}: bad rebalancing {rebalancing!r}")
        self.name = name
        self.weights = dict(weights)
        self.rebalancing = rebalancing
        self.storage = storage or DataStorage.from_config(load_global_config())
        self.slippage_bps_per_leg = float(slippage_bps_per_leg)

    # -------- I/O --------

    def _load_prices(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> pd.DataFrame:
        """Wide adj_close panel for all weighted symbols. Missing series are
        kept (column present, NaN where the ETF didn't trade yet)."""
        frames = {}
        for sym in self.weights:
            df = self.storage.get_prices(sym, start, end)
            if df.empty or "adj_close" not in df.columns:
                frames[sym] = pd.Series(dtype=float, name=sym)
                continue
            s = df["adj_close"].astype(float)
            s.name = sym
            frames[sym] = s
        if not frames:
            return pd.DataFrame()
        panel = pd.concat(frames, axis=1).sort_index()
        if start is not None:
            panel = panel[panel.index >= pd.to_datetime(start)]
        if end is not None:
            panel = panel[panel.index <= pd.to_datetime(end)]
        return panel

    # -------- simulation --------

    def _renormalise(self, target_w: Dict[str, float], available: list[str]) -> Dict[str, float]:
        sub = {k: v for k, v in target_w.items() if k in available and v > 0}
        s = float(sum(sub.values()))
        if s <= 0:
            return {}
        return {k: v / s for k, v in sub.items()}

    def run(
        self,
        start: pd.Timestamp | date | str,
        end: pd.Timestamp | date | str,
        initial_capital_eur: float = 100_000.0,
    ) -> PassivePortfolioResult:
        start_ts = pd.to_datetime(start)
        end_ts = pd.to_datetime(end)
        panel = self._load_prices(start_ts, end_ts)
        if panel.empty:
            raise ValueError(f"{self.name}: empty panel in [{start_ts.date()}, {end_ts.date()}]")

        symbols = list(self.weights.keys())
        dates = panel.index

        # State: shares per symbol (float)
        shares: Dict[str, float] = {s: 0.0 for s in symbols}
        slippage_total = 0.0
        renorm_days = 0
        rebalance_events: list[dict] = []
        equity_series: list[float] = []
        holdings_rows: list[dict] = []
        notes: list[str] = []

        # First-day allocation
        first_d = dates[0]
        avail_first = [s for s in symbols if pd.notna(panel[s].loc[first_d])]
        weights_first = self._renormalise(self.weights, avail_first)
        if len(avail_first) != len(symbols):
            missing = sorted(set(symbols) - set(avail_first))
            notes.append(
                f"At start ({first_d.date()}), {len(missing)} symbol(s) not "
                f"available: {missing}. Their target weights have been "
                f"renormalised onto the remaining {len(avail_first)} symbols."
            )
        cash_left = initial_capital_eur
        for sym, w in weights_first.items():
            price = float(panel[sym].loc[first_d])
            target_eur = initial_capital_eur * w
            shares[sym] = target_eur / price
            cash_left -= target_eur
        # No first-day slippage in this comparison (every allocation pays the
        # same cost to enter — including it would be a wash).

        prev_d = first_d
        prev_avail = set(avail_first)
        for d in dates:
            row_prices = panel.loc[d]
            avail = [s for s in symbols if pd.notna(row_prices[s])]
            if len(avail) != len(symbols):
                renorm_days += 1

            # Detect: a new symbol that didn't exist yesterday but exists today.
            new_today = set(avail) - prev_avail
            force_rebalance_due_to_listing = bool(new_today and len(prev_avail) > 0)
            if force_rebalance_due_to_listing:
                # Note this in the report
                joined = sorted(new_today)
                notes.append(
                    f"{d.date()}: {joined} became tradable — triggering a "
                    f"mid-period rebalance to bring weight up from 0."
                )

            do_rebalance = (
                self.rebalancing != "none" and _is_rebalance_day(d, prev_d, self.rebalancing)
            ) or force_rebalance_due_to_listing

            # Mark to market and (optionally) rebalance
            current_values = {
                s: shares[s] * float(row_prices[s]) if pd.notna(row_prices[s]) else 0.0
                for s in symbols
            }
            equity = sum(current_values.values()) + cash_left

            if do_rebalance:
                target_w = self._renormalise(self.weights, avail)
                # Build target € per symbol (using *current* equity)
                target_eur = {s: equity * w for s, w in target_w.items()}
                # Compute deltas and slippage
                day_slip = 0.0
                for sym in symbols:
                    cur = current_values.get(sym, 0.0)
                    tgt = target_eur.get(sym, 0.0)
                    delta = abs(tgt - cur)
                    day_slip += delta * self.slippage_bps_per_leg / 10_000.0
                # Apply slippage to equity (small)
                equity -= day_slip
                slippage_total += day_slip
                # Reset shares + cash
                cash_left = 0.0
                for sym in symbols:
                    if sym in target_w and pd.notna(row_prices[sym]):
                        shares[sym] = (equity * target_w[sym]) / float(row_prices[sym])
                    else:
                        shares[sym] = 0.0
                # Recompute current_values (post-rebalance) and equity
                current_values = {
                    s: shares[s] * float(row_prices[s]) if pd.notna(row_prices[s]) else 0.0
                    for s in symbols
                }
                # Anything left over after rebalance to a renormalised set goes to cash
                cash_left = equity - sum(current_values.values())
                rebalance_events.append(
                    {
                        "date": d,
                        "slippage_eur": day_slip,
                        "n_active_symbols": len(target_w),
                    }
                )

            equity_series.append(equity)
            holdings_rows.append({"date": d, **current_values, "cash_eur": cash_left})
            prev_d = d
            prev_avail = set(avail)

        equity = pd.Series(equity_series, index=dates, name="equity_eur")
        holdings = pd.DataFrame(holdings_rows).set_index("date")
        rb_df = pd.DataFrame(rebalance_events)

        # Annual returns
        ann = equity.resample("YE").last()
        pre = pd.Series([initial_capital_eur], index=[equity.index[0] - pd.Timedelta(days=1)])
        ann_chain = pd.concat([pre, ann])
        ann_pct = (ann_chain.pct_change() * 100).dropna()
        annual_df = pd.DataFrame(
            {
                "year": ann_chain.index[1:].year,
                "return_pct": ann_pct.values,
            }
        ).reset_index(drop=True)

        # Metrics
        rets = equity.pct_change().dropna()
        n_days = (equity.index[-1] - equity.index[0]).days
        n_years = n_days / 365.25 if n_days > 0 else 0.0
        total_ret = float(equity.iloc[-1] / initial_capital_eur - 1.0)
        cagr = (
            float((equity.iloc[-1] / initial_capital_eur) ** (1 / n_years) - 1.0)
            if n_years > 0
            else float("nan")
        )
        ann_vol = float(rets.std(ddof=1) * math.sqrt(252)) if len(rets) > 1 else 0.0
        sharpe = (
            float(rets.mean() / rets.std(ddof=1) * math.sqrt(252))
            if rets.std(ddof=1) > 0
            else float("nan")
        )
        down = rets[rets < 0]
        dvol = float(down.std(ddof=1) * math.sqrt(252)) if len(down) > 1 else 0.0
        sortino = (
            float(rets.mean() / down.std(ddof=1) * math.sqrt(252)) if dvol > 0 else float("nan")
        )
        rolling_max = equity.cummax()
        dd = equity / rolling_max - 1.0
        max_dd = float(dd.min()) if not dd.empty else 0.0
        trough = dd.idxmin() if not dd.empty else None
        peak = equity.loc[:trough].idxmax() if trough is not None else None
        calmar = float(cagr / abs(max_dd)) if max_dd < 0 else float("nan")

        return PassivePortfolioResult(
            name=self.name,
            weights=self.weights,
            rebalancing=self.rebalancing,
            start_date=equity.index[0],
            end_date=equity.index[-1],
            initial_capital_eur=float(initial_capital_eur),
            final_equity_eur=float(equity.iloc[-1]),
            daily_equity=equity,
            annual_returns=annual_df,
            holdings_history=holdings,
            rebalance_events=rb_df,
            cagr=cagr,
            sharpe=sharpe,
            sortino=sortino,
            calmar=calmar,
            max_drawdown=max_dd,
            max_dd_peak=peak,
            max_dd_trough=trough,
            annualized_vol=ann_vol,
            total_return_pct=total_ret * 100,
            total_slippage_cost_eur=float(slippage_total),
            renormalisation_days=int(renorm_days),
            notes=notes,
        )
