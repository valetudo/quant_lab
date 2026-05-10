"""Generic CSV/Parquet/JSON writers used by analytics and the dashboard."""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd


def write_json(obj: dict, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    return p


def write_csv(df: pd.DataFrame, path: str | Path, **kwargs) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, **kwargs)
    return p
