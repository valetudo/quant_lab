"""Populate <data_storage_path>/prices/{country}/{universe}/{symbol}.parquet from FMP.

Universes (10y of history, 2016-01-01 -> today by default):
  - us/sp500/        : S&P 500 current constituents (~503 symbols)
  - uk/ftse100/      : FTSE 100 curated constituents (~90 symbols)
  - etf/             : SPY, IEF, TLT, BND, AGG, IEI, HYG, LQD
  - indices/         : ^GSPC, ^VIX (^TNX blocked at the current FMP tier;
                       use treasury-rates endpoint for 10y yield instead)

Behaviour:
  - Resumable: skips symbols that already have an up-to-date parquet.
  - Existing data_storage/_legacy/<timestamp>/ snapshot is taken once if
    any prices/ subdirectory already exists (we don't here, since this
    is the first FMP migration).
  - Generates an audit report at the end with success/fail counts.
  - Tracks API call count (FMP usage stays well under the 750/min Premium ceiling).
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from datetime import date, datetime
from pathlib import Path

# --- bootstrap ---
_REPO_ROOT = Path(__file__).resolve().parents[1]
_PARENT = _REPO_ROOT.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))
# ---

import pandas as pd
from tqdm import tqdm

from quant_lab.core.data.providers.fmp_provider import FMPProvider
from quant_lab.core.data.storage import load_global_config


log = logging.getLogger("migrate_prices")


# ---- universe definitions ------------------------------------------------

ETF_LIST = ["SPY", "IEF", "TLT", "BND", "AGG", "IEI", "HYG", "LQD", "VTI", "QQQ"]

INDICES_LIST = ["^GSPC", "^VIX"]  # ^TNX requires higher tier; treasury-rates covers 10y


def universe_paths(prices_root: Path) -> dict[str, Path]:
    """Return the expected directories per universe."""
    return {
        "us/sp500":   prices_root / "us" / "sp500",
        "uk/ftse100": prices_root / "uk" / "ftse100",
        "etf":        prices_root / "etf",
        "indices":    prices_root / "indices",
    }


def _backup_legacy(prices_root: Path) -> Path | None:
    """If prices/ already has content, snapshot it to data_storage/_legacy/<ts>/."""
    if not prices_root.exists() or not any(prices_root.iterdir()):
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = prices_root.parent / "_legacy" / ts / "prices"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(prices_root, backup)
    log.info("backed up existing prices/ -> %s", backup)
    return backup


def _save_symbol(df: pd.DataFrame, universe_dir: Path, symbol: str) -> Path:
    universe_dir.mkdir(parents=True, exist_ok=True)
    safe_sym = symbol.replace("^", "_idx_").replace("/", "_").replace(".", "_")
    out_path = universe_dir / f"{safe_sym}.parquet"
    out = df.copy().reset_index().rename(columns={"index": "date"})
    out["date"] = pd.to_datetime(out["date"])
    out["symbol"] = symbol
    cols = ["symbol", "date", "open", "high", "low", "close", "adj_close", "volume"]
    for c in cols:
        if c not in out.columns:
            out[c] = None
    out[cols].to_parquet(out_path, index=False, compression="snappy")
    return out_path


def _is_fresh(parquet_path: Path, end: date, tolerance_days: int = 7) -> bool:
    if not parquet_path.exists():
        return False
    try:
        df = pd.read_parquet(parquet_path)
        if df.empty:
            return False
        max_d = pd.to_datetime(df["date"]).max().date()
        return (end - max_d).days <= tolerance_days
    except Exception:
        return False


def migrate_universe(
    fmp: FMPProvider,
    symbols: list[str],
    universe_dir: Path,
    start: date,
    end: date,
    *,
    force: bool = False,
) -> dict:
    """Returns {symbol: status} where status in {ok, skipped, empty, error}."""
    results: dict[str, str] = {}
    universe_dir.mkdir(parents=True, exist_ok=True)
    pbar = tqdm(symbols, desc=universe_dir.name, unit="sym", leave=False)
    for sym in pbar:
        safe_sym = sym.replace("^", "_idx_").replace("/", "_").replace(".", "_")
        out_path = universe_dir / f"{safe_sym}.parquet"
        if not force and _is_fresh(out_path, end):
            results[sym] = "skipped"
            continue
        try:
            df = fmp.get_historical_prices(sym, start, end)
            if df.empty:
                results[sym] = "empty"
                continue
            _save_symbol(df, universe_dir, sym)
            results[sym] = "ok"
        except Exception as e:
            log.warning("failed %s: %s", sym, e)
            results[sym] = "error"
        pbar.set_postfix({k: sum(1 for v in results.values() if v == k)
                          for k in ("ok", "skipped", "empty", "error")})
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default="2016-01-01", type=date.fromisoformat)
    ap.add_argument("--end", default=date.today().isoformat(), type=date.fromisoformat)
    ap.add_argument("--force", action="store_true", help="ignore freshness, refetch all")
    ap.add_argument("--universes", nargs="+", default=None,
                    help="subset: any of us/sp500, uk/ftse100, etf, indices")
    ap.add_argument("--out-root", default=None,
                    help="override prices root (default: <data_storage_path>/prices)")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap each universe to N symbols (smoke test)")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = load_global_config()
    data_root = Path(cfg.get("data_storage_path") or
                     (_REPO_ROOT / "data_storage"))
    prices_root = Path(args.out_root) if args.out_root else (data_root / "prices")
    log.info("prices root: %s", prices_root)
    log.info("window: %s -> %s", args.start, args.end)

    fmp = FMPProvider()

    _backup_legacy(prices_root)

    # Build list of universes to migrate
    paths = universe_paths(prices_root)
    selected = list(paths.keys()) if not args.universes else [u for u in args.universes if u in paths]
    log.info("universes: %s", selected)

    sp500_symbols: list[str] = []
    ftse100_symbols: list[str] = []
    overall: dict[str, dict[str, str]] = {}

    t_start = time.monotonic()

    if "us/sp500" in selected:
        log.info("fetching S&P 500 constituents...")
        sp500_symbols = fmp.get_index_constituents("sp500")
        if args.limit:
            sp500_symbols = sp500_symbols[:args.limit]
        log.info("S&P 500: %d symbols", len(sp500_symbols))
        overall["us/sp500"] = migrate_universe(
            fmp, sp500_symbols, paths["us/sp500"], args.start, args.end, force=args.force
        )

    if "uk/ftse100" in selected:
        ftse100_symbols = fmp.get_ftse100_constituents()
        if args.limit:
            ftse100_symbols = ftse100_symbols[:args.limit]
        log.info("FTSE 100: %d symbols", len(ftse100_symbols))
        overall["uk/ftse100"] = migrate_universe(
            fmp, ftse100_symbols, paths["uk/ftse100"], args.start, args.end, force=args.force
        )

    if "etf" in selected:
        etf_syms = ETF_LIST[: args.limit] if args.limit else ETF_LIST
        overall["etf"] = migrate_universe(
            fmp, etf_syms, paths["etf"], args.start, args.end, force=args.force
        )

    if "indices" in selected:
        idx_syms = INDICES_LIST[: args.limit] if args.limit else INDICES_LIST
        overall["indices"] = migrate_universe(
            fmp, idx_syms, paths["indices"], args.start, args.end, force=args.force
        )

    elapsed = time.monotonic() - t_start

    # ---- audit report -------------------------------------------------
    summary: dict = {
        "started_at": datetime.utcnow().isoformat(),
        "window": {"start": str(args.start), "end": str(args.end)},
        "elapsed_seconds": round(elapsed, 1),
        "universes": {},
        "fmp_cache_stats": {
            "hits": fmp.cache.stats.hits,
            "misses": fmp.cache.stats.misses,
            "writes": fmp.cache.stats.writes,
        },
    }
    for uname, res in overall.items():
        counts = {k: sum(1 for v in res.values() if v == k)
                  for k in ("ok", "skipped", "empty", "error")}
        counts["total"] = len(res)
        summary["universes"][uname] = counts
    print(json.dumps(summary, indent=2, default=str))

    # Persist audit
    audit_dir = _REPO_ROOT / "outputs" / "migration_prices"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / f"audit_{datetime.now():%Y%m%d_%H%M%S}.json"
    audit_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    log.info("audit -> %s", audit_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
