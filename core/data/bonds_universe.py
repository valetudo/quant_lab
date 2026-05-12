"""Bonds universe loader + enricher for the LadderBuilder.

Wraps :class:`core.data.providers.borsa_italiana_provider.BorsaItalianaProvider`
(which already gives us ``net_yield_pa``, ``years_to_maturity``,
``is_callable``, ``inflation_linked``, etc.) and adds the columns the
ladder builder needs but the underlying schema doesn't carry directly:

- ``category``          — ``"gov_ita"`` / ``"gov_foreign"`` / ``"corp"``
- ``issuer``            — best-effort parsed from ``name`` (Italian state +
                          short issuer name for corporates)
- ``rating_score``      — int rating, 1 (AAA) … 22 (D); 99 if unknown
- ``is_subordinated``   — pattern match on ``name`` (SUB / SUBORD / AT1 / PERP)
- ``lot_size_eur``      — defaults to 1000 (face value) — almost always
                          correct for Italian retail-listed bonds.
- ``coupon_rate``       — coupon as a decimal (DB stores it as %)
- ``coupon_frequency``  — default 1 (annual); the DB doesn't record it.
- ``yield_net``         — alias for ``net_yield_pa`` (decimal)
- ``price_clean``       — alias for ``latest_price``

Missing fields gracefully degrade — the builder's filters check for ``NaN``
and either skip the filter or exclude the bond, never crash.

The data gap inventory is documented in
``_migration_log/bonds_db_data_gaps.md``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pandas as pd

# Rating scale: lower number = better credit. 99 = unknown.
RATING_SCALE: dict[str, int] = {
    "AAA": 1,
    "AA+": 2,
    "AA": 3,
    "AA-": 4,
    "A+": 5,
    "A": 6,
    "A-": 7,
    "BBB+": 8,
    "BBB": 9,
    "BBB-": 10,
    "BB+": 11,
    "BB": 12,
    "BB-": 13,
    "B+": 14,
    "B": 15,
    "B-": 16,
    "CCC+": 17,
    "CCC": 18,
    "CCC-": 19,
    "CC": 20,
    "C": 21,
    "D": 22,
}


def rating_score(rating: Optional[str]) -> int:
    """Map an S&P/Fitch-style letter rating to a comparable integer score.

    Lower is better (AAA → 1, D → 22). Unknown returns 99.
    """
    if rating is None or (isinstance(rating, float) and pd.isna(rating)):
        return 99
    return RATING_SCALE.get(str(rating).strip().upper(), 99)


# Country-level sovereign rating fallback (S&P 2026Q1 long-term FC).
# Used when the bond row itself carries no rating — true for nearly all
# rows in this DB. Keys are the Italian nation labels used by the scraper.
SOVEREIGN_RATING: dict[str, str] = {
    "Italia": "BBB",
    "Germania": "AAA",
    "Stati Uniti": "AA+",
    "Francia": "AA-",
    "Spagna": "A",
    "Olanda": "AAA",
    "Belgio": "AA",
    "Austria": "AA+",
    "Finlandia": "AA+",
    "Irlanda": "AA",
    "Portogallo": "A-",
    "Lussemburgo": "AAA",
    "Gran Bretagna": "AA",
    "Svezia": "AAA",
    "Polonia": "A-",
    "Cipro": "BBB",
    "Slovenia": "AA-",
    "Lituania": "A",
    "Lettonia": "A",
    "Estonia": "AA-",
    "Croazia": "A-",
    "Bulgaria": "BBB",
    "Romania": "BBB-",
    "Ungheria": "BBB-",
    "Grecia": "BBB-",
    "Cina, Repubblica Popolare Della": "A+",
    "Filippine": "BBB+",
    "Costa D Avorio": "BB",
    "Honduras": "B+",
}


_SUBORDINATED_PATTERNS = re.compile(
    r"\b(SUB|SUBORD|SUBORDIN|AT1|PERP|PERPETUAL|HYBRID|TIER\s*1|TIER\s*2)\b",
    re.IGNORECASE,
)


def is_subordinated(name: str) -> bool:
    if not isinstance(name, str):
        return False
    return bool(_SUBORDINATED_PATTERNS.search(name))


def parse_issuer(name: str, issuer_type: str, nation: Optional[str]) -> str:
    """Best-effort issuer extraction from the bond's display name.

    - Governments collapse to the country name (concentration is intentional
      and bonded by sovereign exposure anyway).
    - Corporates take the first 2 tokens of the name (e.g. "Eni 1.5%..." →
      "Eni"; "Banca Imi Coll..." → "Banca Imi"). Crude but useful as a
      concentration key.
    """
    if not isinstance(name, str) or not name.strip():
        return "UNKNOWN"
    if isinstance(issuer_type, str) and issuer_type.lower() == "government":
        return str(nation) if nation else "UNKNOWN"
    # Corporate: strip leading "Btp" wouldn't apply here. Just take first
    # two tokens before any digit or special char.
    tokens = []
    for tok in re.split(r"\s+", name.strip()):
        if not tok:
            continue
        # Stop at first token that contains a digit (coupon, year, %, etc.).
        if re.search(r"\d", tok):
            break
        tokens.append(tok)
        if len(tokens) >= 2:
            break
    return " ".join(tokens) if tokens else name.split()[0]


def _categorize(row) -> str:
    issuer_type = str(row.get("issuer_type") or "").lower()
    nation = str(row.get("nation") or "").strip()
    if "government" in issuer_type or "sovereign" in issuer_type:
        return "gov_ita" if nation in ("Italia", "Italy", "IT") else "gov_foreign"
    return "corp"


class BondsUniverseLoader:
    """Load + enrich the bonds universe for the LadderBuilder.

    ``load(config)`` returns a pandas DataFrame with at minimum:

    - ``isin``, ``name``, ``issuer``, ``category``, ``nation``, ``currency``
    - ``maturity_date`` (Timestamp), ``years_to_maturity``
    - ``coupon_rate`` (decimal), ``coupon_frequency`` (int)
    - ``price_clean`` (% of face), ``yield_net`` (decimal)
    - ``lot_size_eur``
    - ``rating``, ``rating_score``
    - ``is_subordinated``, ``is_callable``
    """

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        self.db_path = Path(db_path) if db_path else None

    # -------- public --------

    def load(self, config) -> pd.DataFrame:
        """Load + apply universal filters keyed off ``config``.

        ``config`` is a :class:`LadderBuilderConfig` (duck-typed: we read
        ``corp_currency``, ``corp_exclude_subordinated``,
        ``corp_exclude_callable_within_years``).
        """
        df = self._load_raw()
        if df.empty:
            return df

        today = pd.Timestamp.today().normalize()
        df["maturity_date"] = pd.to_datetime(df["maturity_date"], errors="coerce")
        df = df[df["maturity_date"].notna()]
        df = df[df["maturity_date"] > today]

        # Currency filter (EUR for both corp and gov foreign — by design).
        df = df[df["currency"] == config.corp_currency]

        # Enrichments
        df["category"] = df.apply(_categorize, axis=1)
        df["issuer"] = df.apply(
            lambda r: parse_issuer(r.get("name", ""), r.get("issuer_type", ""), r.get("nation")),
            axis=1,
        )
        df["is_subordinated"] = df["name"].apply(is_subordinated)
        # `is_callable` already in BorsaItalianaProvider (name-pattern match).
        if "is_callable" not in df.columns:
            df["is_callable"] = False

        # Rating: prefer per-row if present (none in current schema), else
        # fall back to sovereign rating table for govt bonds.
        if "rating" not in df.columns:
            df["rating"] = None
        df["rating"] = df.apply(self._fill_rating, axis=1)
        df["rating_score"] = df["rating"].apply(rating_score)

        # Numeric normalisations
        # The DB stores `coupon` as %. We expose `coupon_rate` as decimal.
        df["coupon_rate"] = pd.to_numeric(df["coupon"], errors="coerce").fillna(0) / 100.0
        df["coupon_frequency"] = 1  # default annual — no per-row data
        df["lot_size_eur"] = 1000.0  # Italian retail default for EUR bonds

        # Yield alias. The provider returns ``net_yield_pa`` as a percentage
        # (e.g. 2.6 = 2.6 %), so we convert to decimal for internal use.
        if "net_yield_pa" in df.columns:
            df["yield_net"] = pd.to_numeric(df["net_yield_pa"], errors="coerce") / 100.0
        else:
            df["yield_net"] = float("nan")

        # Price alias
        if "latest_price" in df.columns:
            df["price_clean"] = pd.to_numeric(df["latest_price"], errors="coerce")
        else:
            df["price_clean"] = float("nan")

        # Drop rows we cannot price (no latest_price → cannot compute lots).
        df = df[df["price_clean"].notna() & (df["price_clean"] > 0)]

        # Apply universal exclusions
        if config.corp_exclude_subordinated:
            df = df[~df["is_subordinated"]]

        if config.corp_exclude_callable_within_years > 0:
            # Without a per-row first_call_date, we conservatively drop any
            # callable bond. This is over-restrictive but safe.
            df = df[~df["is_callable"].fillna(False)]

        return df.reset_index(drop=True)

    # -------- internals --------

    def _load_raw(self) -> pd.DataFrame:
        """Delegate to BorsaItalianaProvider so we inherit yield computation
        and other enrichments. Falls back to the global-config bonds path
        when no explicit ``db_path`` was provided.
        """
        from core.data.providers.borsa_italiana_provider import BorsaItalianaProvider

        path = self.db_path
        if path is None:
            try:
                from core.data.storage import DataStorage, load_global_config

                storage = DataStorage.from_config(load_global_config())
                path = storage.bonds_db_path
            except Exception:
                path = None
        provider = BorsaItalianaProvider(db_path=path)
        return provider.list_bonds_df(enrich=True)

    def _fill_rating(self, row) -> Optional[str]:
        existing = row.get("rating")
        if existing and isinstance(existing, str) and existing.strip():
            return existing.strip().upper()
        # Fallback: country sovereign rating
        nation = row.get("nation")
        if isinstance(nation, str):
            return SOVEREIGN_RATING.get(nation)
        return None
