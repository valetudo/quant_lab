"""Portfolio-level report generation. Scaffold."""

from __future__ import annotations

import json
from pathlib import Path


def write_portfolio_report(outputs: dict, dest: str | Path) -> Path:
    """Write a single-file summary JSON aggregating per-strategy metrics."""
    p = Path(dest)
    p.parent.mkdir(parents=True, exist_ok=True)
    summary = {sid: o["metrics"] for sid, o in outputs.items()}
    p.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return p
