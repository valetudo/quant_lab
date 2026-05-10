"""Run a backtest from the CLI and write standard outputs.

Usage:
    python scripts/run_backtests.py --strategy dummy_buy_and_hold \\
        --start 2022-01-01 --end 2023-12-31
    python scripts/run_backtests.py --strategy bonds_income \\
        --start 2024-01-01 --end 2025-12-31
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

# --- bootstrap: make `import quant_lab` resolve without pip install ---
_REPO_ROOT = Path(__file__).resolve().parents[1]
_PARENT = _REPO_ROOT.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))
# ---

import numpy as np
import pandas as pd

from quant_lab.core.analytics.metrics import compute_metrics
from quant_lab.core.backtest.engine import PortfolioBacktester
from quant_lab.core.data.storage import DataStorage, load_global_config
from quant_lab.core.io.standard_schema import write_standard_outputs


log = logging.getLogger("run_backtests")


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _make_strategy(strategy_id: str, *, storage: DataStorage, capital: float):
    if strategy_id == "dummy_buy_and_hold":
        from quant_lab.strategies._examples import DummyBuyAndHold
        return DummyBuyAndHold(tickers=["AAPL", "MSFT", "SPY"],
                               initial_capital_eur=capital)
    if strategy_id == "bonds_income":
        from quant_lab.core.data.providers.borsa_italiana_provider import BorsaItalianaProvider
        from quant_lab.strategies.bonds_income import BondsIncome
        provider = BorsaItalianaProvider(db_path=storage.bonds_db_path) \
            if storage.bonds_db_exists() else None
        return BondsIncome(bonds_provider=provider, initial_capital_eur=capital)
    raise SystemExit(f"unknown strategy: {strategy_id}")


def _build_panel(strategy_id: str, start: date, end: date,
                 storage: DataStorage) -> pd.DataFrame:
    if strategy_id == "bonds_income":
        # Synthetic flat panel keyed by ALL current ISINs so the strategy's
        # selected bonds always have a price column.
        provider = None
        if storage.bonds_db_exists():
            from quant_lab.core.data.providers.borsa_italiana_provider import BorsaItalianaProvider
            provider = BorsaItalianaProvider(db_path=storage.bonds_db_path)
        isins = []
        if provider is not None:
            isins = [b["isin"] for b in provider.list_bonds()]
        if not isins:
            isins = [f"MOCK_{i:03d}" for i in range(5)]
        idx = pd.bdate_range(start, end)
        if len(idx) == 0:
            return pd.DataFrame()
        return pd.DataFrame(100.0, index=idx, columns=isins)
    # equity strategies: try DuckDB first, synthetic fallback
    tickers = ["AAPL", "MSFT", "SPY"]
    panel = storage.load_panel(tickers, start, end)
    if not panel.empty:
        return panel
    idx = pd.bdate_range(start, end)
    rng = np.random.default_rng(42)
    rets = rng.normal(0.0005, 0.01, size=(len(idx), len(tickers)))
    prices = 100 * np.cumprod(1 + rets, axis=0)
    return pd.DataFrame(prices, index=idx, columns=tickers)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run a quant_lab backtest")
    ap.add_argument("--strategy", required=True,
                    choices=["dummy_buy_and_hold", "bonds_income"])
    ap.add_argument("--start", required=True, type=_parse_date)
    ap.add_argument("--end", required=True, type=_parse_date)
    ap.add_argument("--capital", type=float, default=None)
    ap.add_argument("--commission-bps", type=float, default=5.0)
    ap.add_argument("--slippage-bps", type=float, default=5.0)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = load_global_config()
    storage = DataStorage.from_config(cfg)
    capital = args.capital if args.capital is not None else float(cfg.get("initial_capital_eur", 50_000))

    panel = _build_panel(args.strategy, args.start, args.end, storage)
    if panel.empty:
        log.error("Empty panel — aborting.")
        return 2

    strat = _make_strategy(args.strategy, storage=storage, capital=capital)
    bt = PortfolioBacktester(
        strat, panel, initial_capital_eur=capital,
        commission_bps=args.commission_bps, slippage_bps=args.slippage_bps,
    )
    log.info("running %s on %d bars × %d cols", args.strategy, *panel.shape)
    res = bt.run()

    eq = res.equity["equity"] if not res.equity.empty else pd.Series(dtype=float)
    metrics = compute_metrics(eq, res.trades, capital,
                              open_count=res.open_count, exposure=res.exposure)

    repo_root = Path(__file__).resolve().parents[1]
    out_dir = Path(args.out_dir) if args.out_dir else (
        repo_root / "outputs" / args.strategy / f"{args.start}_{args.end}"
    )
    paths = write_standard_outputs(
        out_dir,
        strategy_id=args.strategy, universe=",".join(panel.columns[:5]) + "...",
        currency="EUR", trades=res.trades, equity=res.equity,
        open_count=res.open_count, metrics=metrics,
        period_start=args.start, period_end=args.end,
    )
    log.info("trades=%d, sharpe=%.2f, final_eq=%.0f",
             metrics.get("n_trades", 0), metrics.get("sharpe", 0) or 0,
             metrics.get("final_equity", 0) or 0)
    for k, p in paths.items():
        print(f"{k}: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
