"""Capital allocator across strategies. Scaffold for Phase 2."""
from __future__ import annotations
import yaml
from pathlib import Path


def load_allocation(path: str | Path) -> dict[str, float]:
    """Load fraction-per-strategy from a YAML file. Fractions must sum to 1.0."""
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    alloc = cfg.get("allocation", {})
    total = sum(alloc.values())
    if total <= 0 or abs(total - 1.0) > 1e-6:
        raise ValueError(f"allocation fractions must sum to 1.0; got {total}")
    return {k: float(v) for k, v in alloc.items()}
