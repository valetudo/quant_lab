"""Root conftest — make top-level packages importable without `pip install`.

The project is run directly from this directory in phase 1-2 (no editable
install). We insert the repo root into ``sys.path`` so that ``from core...``,
``from strategies...``, ``from portfolio...`` etc. resolve regardless of where
pytest or scripts are invoked from.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Load .env if present so tests that need FMP_API_KEY (or other secrets)
# can see it. Never echoes any value.
try:
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass
