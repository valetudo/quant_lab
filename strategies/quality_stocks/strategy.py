"""QualityStocks — long-only S&P 500 quality + momentum strategy.

Reference: Quantopian "Quality Stocks" (see docs/quantopian_archive/, plan).

Logic per rebalance:
  1. Universe: S&P 500 ex-Financial Services.
  2. Trend filter: SPY SMA(50) > SMA(200)?
  3. Per-name quality score: composite percentile rank of ROIC, FCF yield,
     cash return, 1/debt-equity, and ROIC stability (5y mean/std).
  4. Per-name momentum: log(p_t-skip / p_t-lookback), default 126/10.
  5. Top `quality_pool` by quality, then top `target_securities` by
     momentum within that pool.
  6. If trend up: open positions for those that aren't already held;
     close positions that aren't in the new pick set.
  7. If trend down: hold existing positions only, no new equity buys;
     allocate residual cash to IEF (bond fallback) sized to the gap.

Point-in-time discipline:
  - Fundamentals are filtered by filing_date <= rebalance_date.
  - Strategy emits a Position 'close' Action via manage_positions BEFORE
    new opens, so cash is freed for replacements.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from quant_lab.core.strategy.base import Strategy
from quant_lab.core.strategy.lifecycle import is_first_of_month
from quant_lab.core.strategy.signals import Action, Position, Signal
from quant_lab.strategies.quality_stocks.factors import (
    calculate_momentum,
    calculate_quality_score,
    extract_quality_factors,
)
from quant_lab.strategies.quality_stocks.regime import is_market_uptrend, regime_label

log = logging.getLogger(__name__)


def _load_config(path: Optional[Path] = None) -> dict:
    p = Path(path) if path else (Path(__file__).resolve().parent / "config.yaml")
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class QualityStocks(Strategy):
    def __init__(
        self,
        *,
        fmp,
        config_path: Optional[Path] = None,
        universe_symbols: Optional[list[str]] = None,
        strategy_id: str = "quality_stocks",
        spy_symbol: str = "SPY",
        bond_symbol: Optional[str] = None,
        prefetch: bool = True,
    ) -> None:
        self._strategy_id = strategy_id
        self.cfg = _load_config(config_path)
        self.fmp = fmp
        self.spy_symbol = spy_symbol
        self.bond_symbol = bond_symbol or self.cfg.get("bond_fallback", "IEF")

        # Universe: caller can pre-filter; otherwise we'll pull S&P 500 on init
        self._universe_in = universe_symbols
        self._universe_cache: list[str] = []
        self._fundamentals: dict[str, dict] = {}  # {symbol: {km: df, ratios: df}}
        self._last_rebalance: Optional[pd.Timestamp] = None
        self._selected_now: list[str] = []
        self._prefetch = prefetch

    # ---- Strategy ABC ----------------------------------------------------

    @property
    def strategy_id(self) -> str:
        return self._strategy_id

    @property
    def universe(self) -> list[str]:
        return list(self._universe_cache)

    def on_init(self, history: pd.DataFrame) -> None:
        if self._universe_in is not None:
            symbols = list(self._universe_in)
        else:
            symbols = self.fmp.get_index_constituents("sp500")
        # Filter to symbols that ALSO appear in the panel (engine will reject otherwise)
        if not history.empty:
            symbols = [s for s in symbols if s in history.columns]
        self._universe_cache = symbols
        log.info("quality_stocks universe: %d symbols", len(symbols))

        if self._prefetch:
            self._prefetch_fundamentals(symbols)

    def _prefetch_fundamentals(self, symbols: list[str]) -> None:
        """Pull key-metrics + ratios for each symbol. Cached after first call."""
        log.info("prefetching fundamentals for %d symbols...", len(symbols))
        from tqdm import tqdm
        for s in tqdm(symbols, desc="fundamentals", unit="sym", leave=False):
            try:
                km = self.fmp.get_key_metrics(s, period="annual", limit=10)
                rt = self.fmp.get_ratios(s, period="annual", limit=10)
                self._fundamentals[s] = {"km": km, "ratios": rt}
            except Exception as e:
                log.warning("fundamentals fetch failed for %s: %s", s, e)

    def _get_fundamentals(self, symbol: str):
        if symbol not in self._fundamentals:
            try:
                km = self.fmp.get_key_metrics(symbol, period="annual", limit=10)
                rt = self.fmp.get_ratios(symbol, period="annual", limit=10)
                self._fundamentals[symbol] = {"km": km, "ratios": rt}
            except Exception:
                self._fundamentals[symbol] = {"km": pd.DataFrame(), "ratios": pd.DataFrame()}
        return self._fundamentals[symbol]

    # ---- rebalance cadence ----------------------------------------------

    def _due_for_rebalance(self, date: pd.Timestamp, history: pd.DataFrame) -> bool:
        freq = self.cfg.get("rebalance_frequency", "monthly")
        if freq == "monthly":
            return is_first_of_month(date, history)
        if freq == "weekly":
            return date.weekday() == 0
        if freq == "quarterly":
            return date.month in (1, 4, 7, 10) and is_first_of_month(date, history)
        return is_first_of_month(date, history)

    # ---- selection ------------------------------------------------------

    def _select_picks(self, date: pd.Timestamp, history: pd.DataFrame) -> list[str]:
        """Returns the ordered list of symbols to hold from this rebalance forward."""
        # Quality factors
        factor_rows = {}
        for s in self._universe_cache:
            fd = self._get_fundamentals(s)
            f = extract_quality_factors(s, date, fd["km"], fd["ratios"])
            if f:
                factor_rows[s] = f
        if not factor_rows:
            return []
        ft = pd.DataFrame(factor_rows).T
        weights = self.cfg.get("quality_weights") or None
        quality = calculate_quality_score(ft, weights=weights)
        if quality.empty:
            return []
        top_q = quality.head(int(self.cfg.get("quality_pool", 50))).index.tolist()

        # Momentum
        mom = calculate_momentum(
            history, top_q, date,
            lookback_days=int(self.cfg.get("momentum_lookback", 126)),
            skip_days=int(self.cfg.get("momentum_skip", 10)),
        )
        if mom.empty:
            return top_q[: int(self.cfg.get("target_securities", 20))]
        return mom.head(int(self.cfg.get("target_securities", 20))).index.tolist()

    # ---- engine hooks ---------------------------------------------------

    def generate_signals(
        self,
        date: pd.Timestamp,
        history: pd.DataFrame,
        open_positions: list[Position],
    ) -> list[Signal]:
        first_bar = len(history) == 1
        if not first_bar and not self._due_for_rebalance(date, history):
            return []
        # Build SPY series for regime filter
        spy_series = history[self.spy_symbol] if self.spy_symbol in history.columns else None
        uptrend = is_market_uptrend(spy_series, date) if spy_series is not None else True
        regime = regime_label(spy_series, date) if spy_series is not None else "unknown"

        picks = self._select_picks(date, history)
        self._selected_now = picks
        self._last_rebalance = date

        per_leg = float(self.cfg.get("capital_per_position_eur", 5000))
        held_symbols = {p.instruments[0] for p in open_positions
                        if p.strategy_id == self.strategy_id and p.instruments}

        signals: list[Signal] = []
        if uptrend:
            # Open positions for new picks, leave existing alone (manage_positions
            # closes dropped names so cash is freed before these fills).
            for sym in picks:
                if sym in held_symbols:
                    continue
                if sym not in history.columns or pd.isna(history[sym].loc[date]):
                    continue
                signals.append(Signal(
                    strategy_id=self.strategy_id,
                    instruments=[sym], sides=["long"],
                    target_sizes_eur=[per_leg],
                    metadata={"regime": regime, "rebalance_date": str(date.date())},
                ))
        else:
            # Downtrend: hold whatever's still in the new pick set; do NOT
            # buy more equity. Allocate remaining capital to IEF.
            target_equity = sum(per_leg for s in picks if s in held_symbols)
            total = float(self.cfg.get("initial_capital_eur", 100_000))
            bond_alloc = max(0.0, total - target_equity)
            if (bond_alloc > 0 and self.bond_symbol in history.columns
                    and pd.notna(history[self.bond_symbol].loc[date])):
                # Skip if we already hold the bond
                bond_held = any(p.instruments and p.instruments[0] == self.bond_symbol
                                for p in open_positions
                                if p.strategy_id == self.strategy_id)
                if not bond_held:
                    signals.append(Signal(
                        strategy_id=self.strategy_id,
                        instruments=[self.bond_symbol], sides=["long"],
                        target_sizes_eur=[bond_alloc],
                        metadata={"regime": regime,
                                  "rebalance_date": str(date.date()),
                                  "reason": "bond_fallback"},
                    ))
        return signals

    def manage_positions(
        self,
        date: pd.Timestamp,
        history: pd.DataFrame,
        open_positions: list[Position],
    ) -> list[Action]:
        if not self._due_for_rebalance(date, history):
            return []
        if not self._selected_now:
            # First rebalance not done yet; close nothing.
            return []
        spy_series = history[self.spy_symbol] if self.spy_symbol in history.columns else None
        uptrend = is_market_uptrend(spy_series, date) if spy_series is not None else True

        new_set = set(self._selected_now)
        actions: list[Action] = []
        for pos in open_positions:
            if pos.strategy_id != self.strategy_id or not pos.instruments:
                continue
            sym = pos.instruments[0]
            if sym == self.bond_symbol:
                # Close bond if we go back to uptrend
                if uptrend:
                    actions.append(Action(position_id=pos.position_id,
                                          action="close",
                                          reason="regime_change_uptrend"))
                continue
            if sym not in new_set:
                actions.append(Action(position_id=pos.position_id,
                                      action="close",
                                      reason="rebalance_drop"))
        return actions
