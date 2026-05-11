"""Root conftest — ensures `quant_lab` is importable from the project root.

Adds the project root's parent to sys.path so `from quant_lab.core...`
works even before `pip install -e .` is run. Equivalent of a flat
namespace install for development.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
_PARENT = _REPO_ROOT.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

# Load .env if present so tests that need FMP_API_KEY (or other secrets)
# can see it. Never echoes any value.
try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass
