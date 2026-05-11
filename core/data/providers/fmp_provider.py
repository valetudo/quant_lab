"""FMP (Financial Modeling Prep) provider — Premium plan.

Implements the data-provider contract for prices, fundamentals, key
metrics, ratios, index constituents, and treasury rates. All API
responses are cached in a DuckDB store under `data_storage/cache/`.

Security:
  - The API key is loaded from .env via python-dotenv. It is NEVER
    logged, printed, or written to disk in unmasked form.
  - URLs are sanitised before any log emission (apikey query param
    redacted).

Rate limiting:
  - Token bucket, default 12 calls/second (safety margin below the
    Premium plan's 750/min ceiling).
  - Retries with exponential backoff for HTTP 429 / 5xx / network.

Caching:
  - Historical prices: keyed by (symbol, date). Considered permanent
    once written (date < today).
  - Fundamentals: keyed by (symbol, statement_type, filing_date, period).
  - Cache is read-through (try cache first, fall back to API).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import requests

from quant_lab.core.data.providers.base import BaseProvider

log = logging.getLogger(__name__)


# ---- constants -----------------------------------------------------------

BASE_URL = "https://financialmodelingprep.com/stable"
LEGACY_URL = "https://financialmodelingprep.com/api/v3"

DEFAULT_CALLS_PER_SECOND = 12.0
SLOW_CALLS_PER_SECOND = 6.0  # fallback after repeated 429s


def _mask_key(key: str) -> str:
    if not key or len(key) < 7:
        return "***"
    return f"{key[:3]}...{key[-3:]}"


def _sanitise_url(url: str, key: str) -> str:
    """Replace the apikey in any URL with a masked form before logging."""
    if not key:
        return url
    return url.replace(key, _mask_key(key))


# ---- rate limiter --------------------------------------------------------

class TokenBucket:
    """Simple token-bucket rate limiter (calls per second)."""

    def __init__(self, rate_per_second: float, capacity: Optional[float] = None) -> None:
        self.rate = float(rate_per_second)
        self.capacity = float(capacity if capacity is not None else max(rate_per_second, 1.0))
        self.tokens = self.capacity
        self.timestamp = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> None:
        with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.timestamp
                self.timestamp = now
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return
                wait = (tokens - self.tokens) / self.rate
                time.sleep(max(wait, 0.001))


# ---- cache ---------------------------------------------------------------

_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    symbol VARCHAR,
    date DATE,
    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
    adj_close DOUBLE, volume BIGINT,
    fetched_at TIMESTAMP,
    PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS fundamentals (
    symbol VARCHAR,
    statement_type VARCHAR,
    filing_date DATE,
    period_end_date DATE,
    period VARCHAR,
    data_json VARCHAR,
    fetched_at TIMESTAMP,
    PRIMARY KEY (symbol, statement_type, filing_date, period)
);

CREATE TABLE IF NOT EXISTS index_constituents (
    index_name VARCHAR,
    symbol VARCHAR,
    added_date DATE,
    removed_date DATE,
    PRIMARY KEY (index_name, symbol, added_date)
);

CREATE TABLE IF NOT EXISTS api_calls (
    timestamp TIMESTAMP,
    endpoint VARCHAR,
    symbol VARCHAR,
    http_status INT,
    response_ms INT
);
"""


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    writes: int = 0


class FMPCache:
    """DuckDB-backed cache for FMP responses."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stats = CacheStats()
        self._init_schema()

    def _connect(self):
        import duckdb
        return duckdb.connect(str(self.path))

    def _init_schema(self) -> None:
        with self._connect() as con:
            for stmt in _CACHE_SCHEMA.strip().split(";"):
                s = stmt.strip()
                if s:
                    con.execute(s)

    # ---- prices --------------------------------------------------------

    def get_prices(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        with self._connect() as con:
            df = con.execute(
                """
                SELECT date, open, high, low, close, adj_close, volume
                FROM prices
                WHERE symbol = ? AND date BETWEEN ? AND ?
                ORDER BY date
                """,
                [symbol, start, end],
            ).fetchdf()
        if df.empty:
            self.stats.misses += 1
            return df
        self.stats.hits += 1
        df["date"] = pd.to_datetime(df["date"])
        return df.set_index("date")

    def put_prices(self, symbol: str, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        out = df.copy()
        out["symbol"] = symbol
        out["fetched_at"] = datetime.utcnow()
        out = out.reset_index().rename(columns={"index": "date"})
        # Ensure column set matches schema
        cols = ["symbol", "date", "open", "high", "low", "close",
                "adj_close", "volume", "fetched_at"]
        for c in cols:
            if c not in out.columns:
                out[c] = None
        out = out[cols]
        # Coerce types
        out["date"] = pd.to_datetime(out["date"]).dt.date
        with self._connect() as con:
            con.register("_stage_df", out)
            con.execute(
                "DELETE FROM prices WHERE (symbol, date) IN "
                "(SELECT symbol, date FROM _stage_df)"
            )
            con.execute("INSERT INTO prices SELECT * FROM _stage_df")
            con.unregister("_stage_df")
        self.stats.writes += len(out)
        return len(out)

    def has_prices_for_window(self, symbol: str, start: date, end: date,
                              max_age_days: int = 1) -> bool:
        """Return True iff there is a fresh cache row whose date >= end - 5d.

        Heuristic: if the most recent cached row in the range is at most
        `max_age_days` old (today) or actually equals `end`, we assume
        the cache covers the window.
        """
        with self._connect() as con:
            row = con.execute(
                """
                SELECT MAX(date) AS max_date, MIN(date) AS min_date, COUNT(*) AS n
                FROM prices
                WHERE symbol = ? AND date BETWEEN ? AND ?
                """,
                [symbol, start, end],
            ).fetchone()
        if not row or row[2] == 0:
            return False
        max_d, min_d, n = row
        if min_d > start + timedelta(days=10):
            return False
        # Allow stale cache for ranges that don't include "today"
        today = date.today()
        if end < today - timedelta(days=2):
            return True
        return (today - max_d).days <= max_age_days

    # ---- fundamentals --------------------------------------------------

    def get_fundamentals(self, symbol: str, statement_type: str,
                         period: str = "annual") -> pd.DataFrame:
        with self._connect() as con:
            df = con.execute(
                """
                SELECT symbol, statement_type, filing_date, period_end_date, period, data_json, fetched_at
                FROM fundamentals
                WHERE symbol = ? AND statement_type = ? AND period = ?
                ORDER BY period_end_date DESC
                """,
                [symbol, statement_type, period],
            ).fetchdf()
        if df.empty:
            self.stats.misses += 1
        else:
            self.stats.hits += 1
        return df

    def put_fundamentals(self, symbol: str, statement_type: str,
                         period: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        ins_rows = []
        fetched = datetime.utcnow()
        for r in rows:
            period_end = r.get("date") or r.get("calendarYear") or r.get("fiscalDateEnding")
            filing = r.get("filingDate") or r.get("acceptedDate") or period_end
            try:
                pe = pd.to_datetime(period_end).date() if period_end else None
                fd = pd.to_datetime(filing).date() if filing else pe
            except Exception:
                continue
            if fd is None or pe is None:
                continue
            ins_rows.append((
                symbol, statement_type, fd, pe, period,
                json.dumps(r, default=str), fetched,
            ))
        if not ins_rows:
            return 0
        with self._connect() as con:
            con.executemany(
                """
                INSERT INTO fundamentals
                (symbol, statement_type, filing_date, period_end_date, period, data_json, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (symbol, statement_type, filing_date, period) DO UPDATE SET
                    period_end_date = EXCLUDED.period_end_date,
                    data_json = EXCLUDED.data_json,
                    fetched_at = EXCLUDED.fetched_at
                """,
                ins_rows,
            )
        self.stats.writes += len(ins_rows)
        return len(ins_rows)

    def log_call(self, endpoint: str, symbol: Optional[str], status: int, ms: int) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO api_calls VALUES (?, ?, ?, ?, ?)",
                [datetime.utcnow(), endpoint, symbol, int(status), int(ms)],
            )


# ---- provider ------------------------------------------------------------


class FMPProvider(BaseProvider):
    """Premium FMP provider with caching and rate limiting."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_path: Optional[Path] = None,
        calls_per_second: float = DEFAULT_CALLS_PER_SECOND,
        env_path: Optional[Path] = None,
    ) -> None:
        if api_key is None:
            try:
                from dotenv import load_dotenv
                if env_path is None:
                    # Default: <project_root>/.env (3 parents up from this file)
                    env_path = Path(__file__).resolve().parents[3] / ".env"
                load_dotenv(env_path)
            except ImportError:
                pass
            api_key = os.getenv("FMP_API_KEY")
        if not api_key:
            raise RuntimeError(
                "FMP_API_KEY missing. Set it in .env or pass api_key=..."
            )
        self._api_key = api_key
        # Default cache lives under quant_lab/data_storage/cache/
        if cache_path is None:
            project_root = Path(__file__).resolve().parents[3]
            cache_path = project_root / "data_storage" / "cache" / "fmp_cache.duckdb"
        self.cache = FMPCache(cache_path)
        self._bucket = TokenBucket(rate_per_second=calls_per_second)
        self._consecutive_429 = 0
        self._session = requests.Session()

    @property
    def provider_id(self) -> str:
        return "fmp"

    # ---- low-level GET -------------------------------------------------

    def _get(self, endpoint: str, params: dict, *, base: str = BASE_URL,
             symbol_for_log: Optional[str] = None, max_retries: int = 3):
        """HTTP GET with rate limit, retries, and call logging."""
        params = dict(params or {})
        params["apikey"] = self._api_key
        url = f"{base}/{endpoint}"

        last_exc: Exception | None = None
        for attempt in range(max_retries):
            self._bucket.acquire()
            t0 = time.monotonic()
            try:
                r = self._session.get(url, params=params, timeout=30)
            except (requests.RequestException, OSError) as e:
                last_exc = e
                log.warning("FMP network error on %s (attempt %d/%d): %s",
                            endpoint, attempt + 1, max_retries, e)
                time.sleep(1 + attempt * 2)
                continue
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            try:
                self.cache.log_call(endpoint, symbol_for_log, r.status_code, elapsed_ms)
            except Exception:
                pass
            if r.status_code == 200:
                self._consecutive_429 = 0
                try:
                    return r.json()
                except ValueError as e:
                    log.warning("FMP JSON decode error on %s: %s", endpoint, e)
                    return None
            if r.status_code == 429:
                self._consecutive_429 += 1
                backoff = min(60.0, 1.5 ** (attempt + 1))
                log.warning("FMP 429 on %s (attempt %d/%d). Sleeping %.1fs",
                            endpoint, attempt + 1, max_retries, backoff)
                # If we hit 429 repeatedly, fall back to slow rate
                if self._consecutive_429 >= 3:
                    log.warning("3 consecutive 429s -> reducing rate to %.1f/s",
                                SLOW_CALLS_PER_SECOND)
                    self._bucket = TokenBucket(rate_per_second=SLOW_CALLS_PER_SECOND)
                time.sleep(backoff)
                continue
            if r.status_code == 403:
                log.warning("FMP 403 on %s — plan tier may not include this endpoint", endpoint)
                return None
            if 500 <= r.status_code < 600:
                log.warning("FMP %d on %s (attempt %d/%d)", r.status_code, endpoint,
                            attempt + 1, max_retries)
                time.sleep(1 + attempt * 2)
                continue
            # 4xx other than 429/403: log and bail
            log.warning("FMP HTTP %d on %s: %s", r.status_code, endpoint, r.text[:200])
            return None
        if last_exc:
            log.warning("FMP %s gave up after %d attempts: %s",
                        endpoint, max_retries, last_exc)
        return None

    # ---- public API ----------------------------------------------------

    def get_historical_prices(
        self,
        symbol: str,
        start: date | str,
        end: date | str,
        *,
        adjusted: bool = True,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """Wide-style frame indexed by date with OHLCV + adj_close."""
        if isinstance(start, str):
            start = date.fromisoformat(start)
        if isinstance(end, str):
            end = date.fromisoformat(end)
        if not force_refresh and self.cache.has_prices_for_window(symbol, start, end):
            df = self.cache.get_prices(symbol, start, end)
            if not df.empty:
                return df
        data = self._get(
            "historical-price-eod/full",
            {"symbol": symbol, "from": str(start), "to": str(end)},
            symbol_for_log=symbol,
        )
        if not data or not isinstance(data, list):
            return pd.DataFrame()
        df = pd.DataFrame(data)
        if df.empty:
            return df
        # Field mapping: FMP stable returns close+adjClose+volume
        # but the column set varies slightly; normalise.
        rename = {"adjClose": "adj_close"}
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        if "adj_close" not in df.columns and "close" in df.columns:
            df["adj_close"] = df["close"]
        for c in ("open", "high", "low", "close", "adj_close", "volume"):
            if c not in df.columns:
                df[c] = float("nan")
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").set_index("date")
        df = df[["open", "high", "low", "close", "adj_close", "volume"]]
        # Write to cache
        self.cache.put_prices(symbol, df)
        return df

    def get_historical_prices_batch(
        self,
        symbols: Iterable[str],
        start: date | str,
        end: date | str,
        *,
        force_refresh: bool = False,
        progress: bool = True,
    ) -> dict[str, pd.DataFrame]:
        """Batch wrapper. Returns {symbol: DataFrame}. Skips empties silently."""
        out: dict[str, pd.DataFrame] = {}
        syms = list(symbols)
        iterator = syms
        if progress:
            try:
                from tqdm import tqdm
                iterator = tqdm(syms, desc="FMP prices", unit="sym")
            except ImportError:
                pass
        for sym in iterator:
            try:
                df = self.get_historical_prices(sym, start, end, force_refresh=force_refresh)
                if not df.empty:
                    out[sym] = df
            except Exception as e:
                log.warning("FMP prices failed for %s: %s", sym, e)
        return out

    def get_fundamentals(
        self,
        symbol: str,
        statement_type: str,
        *,
        period: str = "annual",
        limit: int = 20,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """Statement: income-statement | balance-sheet-statement | cash-flow-statement.

        Returns DataFrame with columns derived from JSON + parsed filing_date.
        """
        valid = {"income-statement", "balance-sheet-statement", "cash-flow-statement",
                 "key-metrics", "ratios"}
        if statement_type not in valid:
            raise ValueError(f"unknown statement_type: {statement_type}")

        if not force_refresh:
            cached = self.cache.get_fundamentals(symbol, statement_type, period=period)
            if not cached.empty and len(cached) >= limit:
                # explode data_json
                rows = []
                for _, row in cached.iterrows():
                    try:
                        d = json.loads(row["data_json"])
                    except Exception:
                        continue
                    d["_filing_date"] = row["filing_date"]
                    d["_period_end_date"] = row["period_end_date"]
                    rows.append(d)
                df = pd.DataFrame(rows)
                if not df.empty:
                    df["filing_date"] = pd.to_datetime(df["_filing_date"])
                    df["period_end_date"] = pd.to_datetime(df["_period_end_date"])
                    df = df.sort_values("filing_date", ascending=False)
                    df = df.drop(columns=["_filing_date", "_period_end_date"], errors="ignore")
                    return df.head(limit)

        data = self._get(
            statement_type,
            {"symbol": symbol, "period": period, "limit": limit},
            symbol_for_log=symbol,
        )
        if not data or not isinstance(data, list):
            return pd.DataFrame()
        self.cache.put_fundamentals(symbol, statement_type, period, data)
        df = pd.DataFrame(data)
        if df.empty:
            return df
        # Derive filing_date: prefer explicit, else fall back to fiscal date+90d
        if "filingDate" in df.columns:
            df["filing_date"] = pd.to_datetime(df["filingDate"], errors="coerce")
        elif "acceptedDate" in df.columns:
            df["filing_date"] = pd.to_datetime(df["acceptedDate"], errors="coerce")
        else:
            df["filing_date"] = pd.to_datetime(df.get("date"), errors="coerce") + pd.Timedelta(days=90)
        if "date" in df.columns:
            df["period_end_date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.sort_values("filing_date", ascending=False).head(limit)
        return df

    def get_key_metrics(self, symbol: str, *, period: str = "annual",
                        limit: int = 20, force_refresh: bool = False) -> pd.DataFrame:
        return self.get_fundamentals(symbol, "key-metrics", period=period,
                                     limit=limit, force_refresh=force_refresh)

    def get_ratios(self, symbol: str, *, period: str = "annual",
                   limit: int = 20, force_refresh: bool = False) -> pd.DataFrame:
        return self.get_fundamentals(symbol, "ratios", period=period,
                                     limit=limit, force_refresh=force_refresh)

    # ---- index constituents -------------------------------------------

    def get_index_constituents(self, index: str = "sp500") -> list[str]:
        endpoint = {
            "sp500": "sp500-constituent",
            "nasdaq": "nasdaq-constituent",
            "dowjones": "dowjones-constituent",
        }.get(index.lower())
        if not endpoint:
            raise ValueError(f"unsupported index: {index}")
        data = self._get(endpoint, {})
        if not data or not isinstance(data, list):
            return []
        return sorted({row.get("symbol") for row in data if row.get("symbol")})

    def get_historical_index_constituents(self, index: str = "sp500") -> pd.DataFrame:
        endpoint = {"sp500": "historical-sp500-constituent"}.get(index.lower())
        if not endpoint:
            log.warning("no historical constituents endpoint for %s", index)
            return pd.DataFrame()
        data = self._get(endpoint, {})
        if not data or not isinstance(data, list):
            return pd.DataFrame()
        return pd.DataFrame(data)

    # Curated FTSE 100 list — the LSE screener endpoint returns generic
    # LSE listings (including penny-stock OTCs), so the static list is
    # the authoritative source. Manually maintained against the index.
    _FTSE100_STATIC = [
        "AAL.L", "ABF.L", "AHT.L", "ANTO.L", "AV.L", "AZN.L", "BA.L", "BARC.L",
        "BATS.L", "BDEV.L", "BEZ.L", "BKG.L", "BLND.L", "BNZL.L", "BP.L",
        "BRBY.L", "BT-A.L", "CCH.L", "CNA.L", "CPG.L", "CRDA.L", "CRH.L",
        "CTEC.L", "DCC.L", "DGE.L", "EDV.L", "ENT.L", "EXPN.L", "FCIT.L",
        "FLTR.L", "FRES.L", "GLEN.L", "GSK.L", "HIK.L", "HL.L", "HLMA.L",
        "HSBA.L", "HSX.L", "IAG.L", "ICP.L", "IHG.L", "III.L", "IMB.L",
        "IMI.L", "INF.L", "ITRK.L", "JD.L", "KGF.L", "LAND.L", "LGEN.L",
        "LLOY.L", "LSEG.L", "MNDI.L", "MNG.L", "MRO.L", "NG.L", "NWG.L",
        "NXT.L", "OCDO.L", "PHNX.L", "PRU.L", "PSH.L", "PSN.L", "RIO.L",
        "RKT.L", "RMV.L", "RR.L", "RS1.L", "RTO.L", "SBRY.L", "SDR.L",
        "SGE.L", "SGRO.L", "SHEL.L", "SMDS.L", "SMIN.L", "SMT.L", "SN.L",
        "SPX.L", "SSE.L", "STAN.L", "STJ.L", "SVT.L", "TSCO.L", "TW.L",
        "ULVR.L", "UU.L", "VOD.L", "WEIR.L", "WPP.L", "WTB.L",
    ]

    def get_ftse100_constituents(self) -> list[str]:
        """Curated FTSE 100 ticker list (LSE format with `.L` suffix)."""
        return sorted(set(self._FTSE100_STATIC))

    # ---- macro ---------------------------------------------------------

    def get_treasury_rates(self, start: Optional[date | str] = None,
                           end: Optional[date | str] = None) -> pd.DataFrame:
        params = {}
        if start:
            params["from"] = str(start)
        if end:
            params["to"] = str(end)
        data = self._get("treasury-rates", params)
        if not data or not isinstance(data, list):
            return pd.DataFrame()
        df = pd.DataFrame(data)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").set_index("date")
        return df

    # ---- ABC contract -------------------------------------------------

    def refresh(self, *args, **kwargs) -> dict:
        return {"status": "ok", "message": "FMPProvider is read-through; use specific getters."}
