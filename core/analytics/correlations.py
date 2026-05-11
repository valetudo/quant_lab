"""Cross-strategy equity correlation helpers."""

from __future__ import annotations

import pandas as pd


def equity_correlation(equity_dict: dict[str, pd.Series], method: str = "pearson") -> pd.DataFrame:
    """Pairwise correlation matrix on daily returns of N strategies."""
    rets = {k: v.pct_change().dropna() for k, v in equity_dict.items()}
    df = pd.concat(rets, axis=1).dropna(how="any")
    return df.corr(method=method)
