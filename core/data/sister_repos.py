"""Dynamic loader for sister repos.

Quant Lab integrates a few sibling projects that live as independent
git repos next to it on disk (the canonical reference is the bonds/
Selenium scraper at https://github.com/valetudo/bonds). This module
locates those repos at runtime and exposes their Python modules so
Quant Lab can call them without copying their code in-tree.

Why dynamic import? The sister repos have their own release cadence,
own dependencies (Selenium, ChromeDriver), and their own bonds.db.
Mirroring them into core/ would create a maintenance burden and a
divergence risk. Instead we resolve their location at call time and
import on demand.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Optional, Tuple

log = logging.getLogger(__name__)


# Canonical default location on the developer's machine. Override with
# the ``BONDS_REPO_PATH`` environment variable.
_DEFAULT_BONDS_REPO = Path(
    r"G:\Il mio Drive\__NUOVA_STRUTTURA_DOCUMENTI\02_FINANZE"
    r"\trading_systems\bonds"
)


def get_bonds_sister_repo_path() -> Optional[Path]:
    """Return the absolute path of the bonds/ sister repo, or None.

    Resolution order:
      1. ``BONDS_REPO_PATH`` env var (if set and valid).
      2. The Windows default from the developer's box.
      3. A sibling ``../bonds/`` relative to the Quant Lab repo root.
    """
    env_path = os.environ.get("BONDS_REPO_PATH")
    if env_path:
        p = Path(env_path)
        if (p / "scraper.py").exists():
            return p

    if (_DEFAULT_BONDS_REPO / "scraper.py").exists():
        return _DEFAULT_BONDS_REPO

    relative = Path(__file__).resolve().parents[2].parent / "bonds"
    if (relative / "scraper.py").exists():
        return relative

    return None


def import_bonds_scraper() -> Tuple[ModuleType, ModuleType]:
    """Load and return ``(scraper, database)`` from the bonds/ sister repo.

    Raises :class:`ImportError` with a helpful message when the repo is
    not found. The ``sys.path`` mutation is permanent for this Python
    process: re-importing later (e.g. when the worker thread runs) is
    a no-op once the modules are in ``sys.modules``.
    """
    repo_path = get_bonds_sister_repo_path()
    if repo_path is None:
        raise ImportError(
            "Sister repo 'bonds/' non trovato. Posizioni provate:\n"
            f"  - $BONDS_REPO_PATH ({os.environ.get('BONDS_REPO_PATH', '(unset)')})\n"
            f"  - {_DEFAULT_BONDS_REPO}\n"
            f"  - {Path(__file__).resolve().parents[2].parent / 'bonds'}\n"
            "Soluzioni:\n"
            "  1. Clona https://github.com/valetudo/bonds come ../bonds "
            "rispetto a quant_lab/\n"
            "  2. Oppure imposta BONDS_REPO_PATH al percorso assoluto del repo."
        )

    # The sister repo expects to be importable as a flat module set
    # (scraper.py + database.py + calculations.py at the package root).
    # We insert its path at the front of sys.path so its modules win
    # over any same-named modules in Quant Lab (none today, but defensive).
    if str(repo_path) not in sys.path:
        sys.path.insert(0, str(repo_path))

    try:
        import scraper  # type: ignore
        import database as bonds_database  # type: ignore
    except Exception as e:
        # Restore sys.path on failure so a later retry can recover from
        # a transient import error (e.g. selenium not installed yet).
        if str(repo_path) in sys.path:
            sys.path.remove(str(repo_path))
        raise ImportError(
            f"Sister repo trovato a {repo_path} ma l'import ha fallito: {e}. "
            "Controlla che le dipendenze del bonds/ repo siano installate "
            "(selenium, webdriver-manager, beautifulsoup4)."
        ) from e

    log.info("bonds/ sister repo imported from %s", repo_path)
    return scraper, bonds_database
