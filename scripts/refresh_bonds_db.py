"""Refresh ``bonds.db`` from Borsa Italiana.

The full re-scrape pipeline lives in the sister `bonds/` repo
(``G:\\...\\trading_systems\\bonds``). Borsa Italiana's HTML structure
is moderately fragile and the scraping code is non-trivial (~40 KB).
This script does not duplicate it — instead it looks for the sister
repo and copies the freshly-scraped DB over.

If the sister repo is not present, this is a no-op scaffold: it logs a
clear message and returns a structured status dict so the UI banner can
say "scrape-in-place not yet wired, run `bonds/start.bat` separately".

When the bonds repo's scraper is moved into this monorepo (planned),
swap this scaffold for the real entry-point.
"""

from __future__ import annotations

import logging
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def _bonds_repo_path() -> Path:
    """Sister repository expected at ``../bonds/`` relative to this monorepo."""
    return Path(__file__).resolve().parents[2] / "bonds"


def refresh_bonds_db(target_path: Optional[Path] = None) -> dict:
    """Refresh ``bonds.db`` at ``target_path`` (defaults to the configured
    location). Returns a dict::

        {
            "status": "ok" | "scaffold" | "error",
            "n_bonds": int,        # only on success
            "elapsed_sec": float,
            "message": str,
            "source": str,         # path of the source DB
            "target": str,         # path of the destination DB
        }

    Today this just copies the sister repo's DB if present.
    """
    start = time.time()
    if target_path is None:
        try:
            from core.data.storage import DataStorage, load_global_config

            storage = DataStorage.from_config(load_global_config())
            target_path = Path(storage.bonds_db_path)
        except Exception as e:
            return {
                "status": "error",
                "message": f"Could not resolve target bonds.db path: {e}",
                "elapsed_sec": time.time() - start,
            }

    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    sister_db = _bonds_repo_path() / "bonds.db"
    if sister_db.exists():
        # Back up the existing target first.
        if target_path.exists():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = target_path.with_name(f"bonds_backup_{ts}.db")
            try:
                shutil.copy2(target_path, backup)
            except Exception as e:
                log.warning("backup of %s failed: %s", target_path, e)
        try:
            shutil.copy2(sister_db, target_path)
        except Exception as e:
            return {
                "status": "error",
                "message": f"copy failed: {e}",
                "source": str(sister_db),
                "target": str(target_path),
                "elapsed_sec": time.time() - start,
            }
        # Count rows in the copy (cheap).
        n_bonds = None
        try:
            import sqlite3

            with sqlite3.connect(str(target_path)) as conn:
                row = conn.execute("SELECT COUNT(*) FROM bonds").fetchone()
                n_bonds = int(row[0]) if row else None
        except Exception:
            pass
        return {
            "status": "ok",
            "n_bonds": n_bonds,
            "source": str(sister_db),
            "target": str(target_path),
            "elapsed_sec": time.time() - start,
            "message": f"Copiati dati da {sister_db}",
        }

    return {
        "status": "scaffold",
        "message": (
            "Scrape-in-place non ancora implementato in questo repo. "
            "Per ora: esegui `bonds/start.bat` nel repo bonds adiacente, "
            "poi clicca di nuovo questo bottone (copierà il DB aggiornato)."
        ),
        "source": str(sister_db),
        "target": str(target_path),
        "elapsed_sec": time.time() - start,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(refresh_bonds_db(), indent=2, default=str))
