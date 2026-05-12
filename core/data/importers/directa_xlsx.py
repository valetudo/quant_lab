"""Directa XLSX portfolio importer.

Parses the standard portfolio export from Directa
(file pattern: ``P_TOTALE_<account>_<YYYYMMDD>.xlsx``). The format,
verified against a real export:

```
Row 0:  Portafoglio : TOTALE
Row 1:  Conto : <account> <holder>
Row 2:  Data estrazione : YYYY/MM/DD HH:MM:SS
Row 3:  (blank)
Row 4:  Valore portafoglio : <amount>€
Rows 5-6: (blank)
Row 7:  Strumento | Ticker | Isin | Prezzo | Trend % | Quantita |
        Valore di carico | Valore attuale | Gain/Loss € | Gain/Loss % |
        Gain/Loss € Intraday | Prezzo medio | Bid | Ask | Divisa
Row 8+: positions (one per line)
Last row: totals (NaN in Strumento/Isin)
```

Cash balance is NOT in the file — the caller must set it on the returned
:class:`DirectaPortfolioSnapshot` after asking the user.

Asset-class classification is heuristic (pattern matching on name + ISIN
prefix + ticker shape). The classifier is conservative: anything it
cannot map confidently is tagged ``"unknown"`` so the UI can flag it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import pandas as pd

AssetClass = Literal["bond", "equity", "unknown"]


# ---------- bond / equity classification heuristics ----------

_BOND_NAME_SIGNALS = (
    "BTP",
    "BUND",
    "OAT",
    "BONO",
    "BONOS",
    "GILT",
    "TREASURY",
    "USA TF",
    " TF ",
    " FX ",
    "BOND",
    "FINANCE FX",
    "GREEN FX",
    "CUM BONUS",
    "VALORE",
    "EUROTLX",
    "MTS",
    # Sovereign issuer names
    "ROMANIA",
    "SPAIN",
    "SPAGNA",
    "FRANCE",
    "FRANCIA",
    "GERMANY",
    "GERMANIA",
    "ITALY",
    "ITALIA",
    "HUNGARY",
    "PORTUGAL",
    "GRECIA",
    # Italian corporates that issue retail-listed bonds
    "ENI",
    "ENEL",
    "TELECOM",
    "INTESA",
    "UNICREDIT",
    "GENERALI",
    "FERROVIE",
    "POSTE",
    "CARRARO",
    "BANCO BPM",
    "MEDIOBANCA",
    "SNAM",
    "TERNA",
    "ATLANTIA",
    "AUTOSTRADE",
)

_EQUITY_NAME_SIGNALS = (
    "UCITS",
    "ETF",
    " FTSE",
    "MSCI",
    "S&P 500",
    "INDEX FUND",
    "INDEX ETF",
    "VANGUARD",
    "ISHARES",
)


# ---------- dataclasses ----------


@dataclass
class DirectaPosition:
    """A single line of the Directa export."""

    name: str
    ticker: str
    isin: str
    price: float
    quantity: float
    cost_basis_eur: float
    current_value_eur: float
    avg_purchase_price: float
    pnl_eur: float
    pnl_pct: float
    currency: str

    # Derived
    asset_class: AssetClass = "unknown"
    issuer: Optional[str] = None


@dataclass
class DirectaPortfolioSnapshot:
    """Full parsed snapshot of a Directa portfolio export."""

    account: str
    account_holder: str
    extraction_date: pd.Timestamp
    total_portfolio_value_eur: float
    positions: list[DirectaPosition] = field(default_factory=list)

    # Filled by the UI from a separate input (Directa XLSX excludes cash).
    cash_balance_eur: Optional[float] = None

    @property
    def patrimony_total_eur(self) -> float:
        cash = self.cash_balance_eur or 0.0
        return self.total_portfolio_value_eur + cash

    def by_asset_class(self) -> dict[str, list[DirectaPosition]]:
        out: dict[str, list[DirectaPosition]] = {"bond": [], "equity": [], "unknown": []}
        for p in self.positions:
            out.setdefault(p.asset_class, []).append(p)
        return out

    def total_by_asset_class_eur(self) -> dict[str, float]:
        out = {"bond": 0.0, "equity": 0.0, "unknown": 0.0}
        for p in self.positions:
            out[p.asset_class] = out.get(p.asset_class, 0.0) + (p.current_value_eur or 0.0)
        return out


# ---------- helpers ----------


def _parse_italian_amount(text: str) -> float:
    """Parse an italian-formatted currency string like ``169738,86€``
    or ``1.234.567,89€`` to a float.
    """
    cleaned = text.strip()
    # Strip everything after the last digit-ish char (currency / encoding artifacts).
    cleaned = re.sub(r"[^\d,.\-]+$", "", cleaned)
    # Italian convention: comma is decimal, dots are thousands separators.
    cleaned = cleaned.replace(".", "").replace(",", ".")
    return float(cleaned)


def _classify(p: DirectaPosition) -> AssetClass:
    isin = (p.isin or "").upper()
    if len(isin) < 2:
        return "unknown"
    name_upper = (p.name or "").upper()
    country = isin[:2]
    ticker = (p.ticker or "").strip()

    # Strong bond signals from the instrument name.
    if any(sig in name_upper for sig in _BOND_NAME_SIGNALS):
        return "bond"

    # Strong equity ETF signals from the name.
    if any(sig in name_upper for sig in _EQUITY_NAME_SIGNALS):
        return "equity"

    # Ticker patterns:
    #  - Directa bond tickers begin with ``M.`` (e.g. ``M.506794``, ``M.501826_T``).
    #  - Equity tickers begin with ``.`` (e.g. ``.AAPL``, ``.PYPL``).
    if ticker.startswith("M."):
        return "bond"
    if ticker.startswith(".") and country == "US":
        return "equity"

    # IT-issued ISIN without the M. ticker prefix is almost always a stock
    # (IT bonds always use M. on Directa).
    if country == "IT" and not ticker.startswith("M."):
        return "equity"

    return "unknown"


_BOND_NAME_CUT_PATTERNS = (
    re.compile(r"\bTF\b", re.IGNORECASE),
    re.compile(r"\bFX\b", re.IGNORECASE),
    re.compile(r"\d+[.,]?\d*\s*%"),
    re.compile(r"\b\d{4}\b"),  # year
    re.compile(r"\bSC\b", re.IGNORECASE),  # "Senza Cedola" tag on BTP Valore
    re.compile(r"\bCUM\b", re.IGNORECASE),
)


def _extract_issuer(p: DirectaPosition) -> Optional[str]:
    if p.asset_class != "bond" or not p.name:
        return None
    name = p.name.strip()
    cut = len(name)
    for pat in _BOND_NAME_CUT_PATTERNS:
        m = pat.search(name)
        if m:
            cut = min(cut, m.start())
    issuer = name[:cut].strip()
    if not issuer:
        # Fallback: take the first 2 words of the original name.
        tokens = name.split()
        issuer = " ".join(tokens[:2]) if tokens else name
    return issuer


# ---------- parser ----------


class DirectaXLSXImporter:
    """Parse a Directa portfolio XLSX export."""

    HEADER_ROW = 7  # 0-indexed

    def parse(self, file_path: Path | str) -> DirectaPortfolioSnapshot:
        file_path = Path(file_path)
        raw = pd.read_excel(file_path, header=None)
        meta = self._extract_metadata(raw)

        df = pd.read_excel(file_path, header=self.HEADER_ROW)
        # Drop the totals row (NaN in identifier columns) and any empty trailers.
        df = df.dropna(subset=["Strumento", "Isin"]).reset_index(drop=True)

        positions: list[DirectaPosition] = []
        for _, row in df.iterrows():
            p = self._parse_row(row)
            p.asset_class = _classify(p)
            p.issuer = _extract_issuer(p)
            positions.append(p)

        return DirectaPortfolioSnapshot(
            account=meta.get("account", ""),
            account_holder=meta.get("account_holder", ""),
            extraction_date=meta.get("extraction_date", pd.Timestamp.today().normalize()),
            total_portfolio_value_eur=meta.get("total_value_eur", 0.0),
            positions=positions,
        )

    # -------- internals --------

    def _extract_metadata(self, raw: pd.DataFrame) -> dict:
        meta: dict = {}
        for i in range(min(7, len(raw))):
            cell = raw.iloc[i, 0]
            if pd.isna(cell):
                continue
            text = str(cell)
            if "Conto" in text and ":" in text:
                parts = text.split(":", 1)[1].strip().split(" ", 1)
                meta["account"] = parts[0]
                meta["account_holder"] = parts[1] if len(parts) > 1 else ""
            elif "Data estrazione" in text:
                date_str = text.split(":", 1)[1].strip()
                try:
                    meta["extraction_date"] = pd.Timestamp(date_str)
                except Exception:
                    meta["extraction_date"] = pd.Timestamp.today().normalize()
            elif "Valore portafoglio" in text:
                val_str = text.split(":", 1)[1]
                try:
                    meta["total_value_eur"] = _parse_italian_amount(val_str)
                except Exception:
                    meta["total_value_eur"] = 0.0
        return meta

    def _parse_row(self, row: pd.Series) -> DirectaPosition:
        # The Gain/Loss column header uses a literal €. We may have read it
        # back as a mojibake (`Gain/Loss �`) depending on encoding; fall
        # back to substring matching to stay resilient.
        def _get(key_candidates: tuple[str, ...]) -> object:
            for k in row.index:
                for cand in key_candidates:
                    if cand in str(k):
                        return row[k]
            return None

        def _f(val) -> float:
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return 0.0
            try:
                return float(val)
            except (ValueError, TypeError):
                return 0.0

        return DirectaPosition(
            name=str(_get(("Strumento",)) or "").strip(),
            ticker=str(_get(("Ticker",)) or "").strip(),
            isin=str(_get(("Isin", "ISIN")) or "").strip(),
            price=_f(_get(("Prezzo", "Price"))),
            quantity=_f(_get(("Quantita", "Quantità"))),
            cost_basis_eur=_f(_get(("Valore di carico",))),
            current_value_eur=_f(_get(("Valore attuale",))),
            avg_purchase_price=_f(_get(("Prezzo medio",))),
            pnl_eur=_f(_get(("Gain/Loss",))),  # picks the € column first
            pnl_pct=_f(_get(("Gain/Loss %",))),
            currency=str(_get(("Divisa",)) or "EUR").strip(),
        )


def import_directa_xlsx(
    file_path: Path | str,
    cash_balance_eur: Optional[float] = None,
) -> DirectaPortfolioSnapshot:
    """Convenience wrapper. Parse the file and (optionally) set the cash balance."""
    snapshot = DirectaXLSXImporter().parse(file_path)
    if cash_balance_eur is not None:
        snapshot.cash_balance_eur = float(cash_balance_eur)
    return snapshot
