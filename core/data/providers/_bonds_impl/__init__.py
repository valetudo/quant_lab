"""Internal implementation of the Borsa Italiana scraper + SQLite layer.

Imported by `borsa_italiana_provider.py`. Sub-package isolation lets us
keep the original bonds module imports working ("from calculations import …")
via the patched module aliasing below.
"""

from __future__ import annotations

# Make the unqualified `calculations` import inside scraper.py resolve to
# our sub-package module. This avoids editing scraper.py's source.
import sys

from . import calculations as _calculations

sys.modules.setdefault("calculations", _calculations)
