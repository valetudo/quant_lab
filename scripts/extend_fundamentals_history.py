"""Backfill FMP fundamentals (key-metrics + ratios) to ~20 years per symbol.

The existing cache was populated with limit=10 in 2024, so it stops around 2016
filings. The Quality Stocks V5 walk-forward needs older fundamentals to trade
in 2012-2015. This script re-fetches with limit=20 and force_refresh=True for
every current S&P 500 constituent.

Cost: ~500 symbols × 2 statement types = ~1000 API calls. At 12/s ≈ 90s raw,
plus DuckDB inserts ≈ 3-4 min wall time. The FMP Premium plan absorbs this
under its 750/min ceiling.

Idempotent (re-running is wasteful but safe).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# --- bootstrap ---
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# ---

from tqdm import tqdm

from core.data.providers.fmp_provider import FMPProvider

log = logging.getLogger("extend_fundamentals")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--limit", type=int, default=20, help="annual filings to request per symbol (default: 20)"
    )
    ap.add_argument(
        "--statements",
        nargs="+",
        default=["key-metrics", "ratios"],
        help="statement types to refresh",
    )
    ap.add_argument("--max-symbols", type=int, default=None, help="cap for smoke tests")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    fmp = FMPProvider()
    syms = fmp.get_index_constituents("sp500")
    if args.max_symbols:
        syms = syms[: args.max_symbols]
    log.info(
        "refreshing %d statements x %d symbols = %d API calls",
        len(args.statements),
        len(syms),
        len(args.statements) * len(syms),
    )

    counts = {st: {"ok": 0, "empty": 0, "err": 0} for st in args.statements}
    t0 = time.monotonic()
    for sym in tqdm(syms, desc="fundamentals", unit="sym"):
        for st in args.statements:
            try:
                if st == "key-metrics":
                    df = fmp.get_key_metrics(
                        sym, period="annual", limit=args.limit, force_refresh=True
                    )
                elif st == "ratios":
                    df = fmp.get_ratios(sym, period="annual", limit=args.limit, force_refresh=True)
                else:
                    df = fmp.get_fundamentals(
                        sym, st, period="annual", limit=args.limit, force_refresh=True
                    )
                counts[st]["ok" if not df.empty else "empty"] += 1
            except Exception as e:
                counts[st]["err"] += 1
                log.warning("%s/%s: %s", sym, st, e)
    elapsed = time.monotonic() - t0
    print(f"\nElapsed: {elapsed:0.1f}s")
    for st, c in counts.items():
        print(f"  {st}: ok={c['ok']} empty={c['empty']} err={c['err']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
