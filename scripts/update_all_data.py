"""Update all data sources — placeholder.

For equities: defer to global_data_storage's own ingest pipeline
(`uv run scripts/ingest_yfinance.py` or whatever the GDS CLI exposes).

For bonds: run BorsaItalianaProvider.refresh() — this requires the
`scraping` extra (`pip install -e .[scraping]`).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# --- bootstrap ---
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# ---

from core.data.providers.borsa_italiana_provider import BorsaItalianaProvider
from core.data.storage import DataStorage, load_global_config

log = logging.getLogger("update_all_data")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["all", "bonds", "equities"], default="all")
    ap.add_argument("--no-headless", action="store_true", help="show the Selenium browser window")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    cfg = load_global_config()
    storage = DataStorage.from_config(cfg)

    if args.source in ("all", "bonds"):
        if not storage.bonds_db_exists():
            log.error(
                "bonds DB missing at %s — run scripts/migrate_bonds_db.py first",
                storage.bonds_db_path,
            )
        else:
            log.info("refreshing Borsa Italiana scrape into %s", storage.bonds_db_path)
            provider = BorsaItalianaProvider(db_path=storage.bonds_db_path)
            result = provider.refresh(headless=not args.no_headless)
            log.info("bonds refresh: %s", result)

    if args.source in ("all", "equities"):
        log.info(
            "equity data refresh is delegated to global_data_storage. Run its ingest CLI from %s",
            cfg.get("data_storage_path"),
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
