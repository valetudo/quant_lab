"""Copy bonds.db from the original bonds project into the configured bonds_db_path.

Run once after quant_lab is checked out. Idempotent: if the destination
already exists with the same size, it skips.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# --- bootstrap ---
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# ---

import os

from core.data.storage import _project_root, load_global_config

# Default source: a sibling `bonds/` repo next to this monorepo. Override
# via env var QUANT_LAB_BONDS_SOURCE or the --source CLI flag.
_DEFAULT_SOURCE_ENV = os.environ.get("QUANT_LAB_BONDS_SOURCE")
DEFAULT_SOURCE = (
    Path(_DEFAULT_SOURCE_ENV) if _DEFAULT_SOURCE_ENV else (_REPO_ROOT.parent / "bonds" / "bonds.db")
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Migrate bonds.db into the quant_lab data storage path."
    )
    ap.add_argument("--source", default=str(DEFAULT_SOURCE), help="Original bonds.db path")
    ap.add_argument(
        "--dest",
        default=None,
        help="Destination override (default: configs/global.yaml bonds_db_path)",
    )
    args = ap.parse_args(argv)

    src = Path(args.source)
    if not src.exists():
        print(f"[migrate_bonds_db] source not found: {src}", file=sys.stderr)
        return 2

    cfg = load_global_config()
    dest = (
        Path(args.dest)
        if args.dest
        else Path(
            cfg.get("bonds_db_path") or (_project_root() / "data_storage" / "bonds" / "bonds.db")
        )
    )
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and dest.stat().st_size == src.stat().st_size:
        print(f"[migrate_bonds_db] dest already in place: {dest}")
        return 0

    shutil.copy2(src, dest)
    print(f"[migrate_bonds_db] copied {src} -> {dest}  ({dest.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
