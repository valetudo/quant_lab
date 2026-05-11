"""Static universe lists used as defaults for strategies and the UI.

For dynamic / market-scraped universes, query the GDS DuckDB via
`DataStorage.load_universe_meta()`.
"""

from __future__ import annotations

# FTSE MIB (40 names) — Borsa Italiana blue chips. List can drift; verify
# against prices.universe in the DuckDB for the canonical active set.
FTSEMIB: list[str] = [
    "A2A.MI",
    "AMP.MI",
    "AZM.MI",
    "BAMI.MI",
    "BGN.MI",
    "BMED.MI",
    "BPE.MI",
    "BPSO.MI",
    "CPR.MI",
    "DIA.MI",
    "ENEL.MI",
    "ENI.MI",
    "ERG.MI",
    "FBK.MI",
    "G.MI",
    "HER.MI",
    "INW.MI",
    "ISP.MI",
    "IVG.MI",
    "LDO.MI",
    "MB.MI",
    "MONC.MI",
    "NEXI.MI",
    "PIRC.MI",
    "PRY.MI",
    "RACE.MI",
    "REC.MI",
    "SPM.MI",
    "SRG.MI",
    "STLAM.MI",
    "STMMI.MI",
    "TEN.MI",
    "TIT.MI",
    "TRN.MI",
    "UCG.MI",
    "UNI.MI",
    "BAMI.MI",
    "BPSO.MI",
    "BGN.MI",
    "BMED.MI",
]

# FTSE Italia Mid Cap (placeholder — populate from DuckDB universe in fase 2).
FTSE_MID_CAP: list[str] = []

# CAC 40 + a few large French mid caps (used by pair_trading FR variant).
CAC_LARGE_MID: list[str] = [
    "AC.PA",
    "AI.PA",
    "AIR.PA",
    "ALO.PA",
    "BN.PA",
    "BNP.PA",
    "CA.PA",
    "CAP.PA",
    "CS.PA",
    "DG.PA",
    "DSY.PA",
    "EL.PA",
    "EN.PA",
    "ENGI.PA",
    "ERF.PA",
    "FR.PA",
    "GLE.PA",
    "HO.PA",
    "KER.PA",
    "LR.PA",
    "MC.PA",
    "ML.PA",
    "OR.PA",
    "ORA.PA",
    "PUB.PA",
    "RI.PA",
    "RMS.PA",
    "SAF.PA",
    "SAN.PA",
    "SGO.PA",
    "STMPA.PA",
    "SU.PA",
    "SW.PA",
    "TEP.PA",
    "TTE.PA",
    "URW.PA",
    "VIE.PA",
    "VIV.PA",
    "WLN.PA",
]

# S&P 500 proxy (a curated quality-tilted slice used for quality_stocks dev).
SP500_PROXY: list[str] = [
    "AAPL",
    "MSFT",
    "GOOG",
    "GOOGL",
    "META",
    "AMZN",
    "NVDA",
    "JNJ",
    "JPM",
    "V",
    "PG",
    "MA",
    "HD",
    "UNH",
    "XOM",
    "CVX",
    "PFE",
    "ABBV",
    "KO",
    "PEP",
    "WMT",
    "MCD",
    "BAC",
    "CSCO",
    "ORCL",
    "ADBE",
    "CRM",
    "INTC",
    "TXN",
    "QCOM",
]


def get_universe(name: str) -> list[str]:
    name_u = name.upper().replace("-", "_")
    return {
        "FTSEMIB": FTSEMIB,
        "FTSE_MIB": FTSEMIB,
        "FTSE_ITALIA_MID_CAP": FTSE_MID_CAP,
        "CAC_LARGE_MID": CAC_LARGE_MID,
        "SP500_PROXY": SP500_PROXY,
    }.get(name_u, [])


AVAILABLE_UNIVERSES = ["FTSEMIB", "CAC_LARGE_MID", "SP500_PROXY"]


# ---------------------------------------------------------------------------
# Dynamic, FMP-backed universe (Phase S — survivorship correction)
# ---------------------------------------------------------------------------

import pandas as pd  # noqa: E402  (placed at end to keep static lists at top)


class Universe:
    """A named universe whose constituents may be fixed or time-varying.

    Modes:
      - ``current``: always returns today's constituents (back-compat default).
      - ``point_in_time``: at any historical date ``as_of``, reconstructs
        membership using the FMP ``historical-<index>-constituent`` event log.
        Use this for survivorship-bias-corrected backtests.

    The provider must expose ``get_index_constituents()`` and, for
    point_in_time, ``get_constituents_at_date()``.
    """

    def __init__(self, universe_id: str, fmp, *, mode: str = "current") -> None:
        if mode not in ("current", "point_in_time"):
            raise ValueError(f"unknown mode: {mode!r}")
        self.universe_id = universe_id
        self.fmp = fmp
        self.mode = mode

    def get_constituents(self, as_of: pd.Timestamp | None = None) -> list[str]:
        if self.mode == "current" or as_of is None:
            return self.fmp.get_index_constituents(self.universe_id)
        return self.fmp.get_constituents_at_date(self.universe_id, as_of=as_of)
