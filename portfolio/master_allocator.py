"""Deprecated — moved to ``portfolio._legacy.master_allocator``.

Phase 3 replaced the dynamic master-allocator model with a static strategic
allocation (``portfolio.static_allocator``). This module is kept as a thin
re-export so existing scripts and tests continue to import the old symbols.
New code should NOT import from here.
"""

from __future__ import annotations

import warnings

from portfolio._legacy.master_allocator import (  # noqa: F401
    EqualWeightAllocator,
    FixedWeightAllocator,
    MasterAllocator,
    RegimeAwareAllocator,
)

warnings.warn(
    "portfolio.master_allocator is deprecated; use portfolio.static_allocator instead",
    DeprecationWarning,
    stacklevel=2,
)
