"""FMPProvider integration tests — skipped if FMP_API_KEY not set."""

from __future__ import annotations

import os
import time
from datetime import date, timedelta

import pytest

from core.data.providers.fmp_provider import FMPProvider, TokenBucket

pytestmark = pytest.mark.skipif(
    not os.getenv("FMP_API_KEY"),
    reason="FMP_API_KEY not set (load .env to enable these tests)",
)


@pytest.fixture(scope="module")
def fmp(tmp_path_factory):
    cache = tmp_path_factory.mktemp("fmp") / "cache.duckdb"
    return FMPProvider(cache_path=cache)


def test_token_bucket_rate_limits():
    bucket = TokenBucket(rate_per_second=10.0)
    t0 = time.monotonic()
    for _ in range(15):
        bucket.acquire()
    elapsed = time.monotonic() - t0
    # 15 tokens at 10/s with capacity 10: first 10 instant, next 5 take ~0.5s
    assert 0.3 < elapsed < 1.5, f"unexpected throttle behaviour: {elapsed:.2f}s"


def test_historical_prices_aapl(fmp):
    end = date.today()
    start = end - timedelta(days=45)
    df = fmp.get_historical_prices("AAPL", start, end)
    assert not df.empty
    assert len(df) >= 15
    for col in ("open", "high", "low", "close", "adj_close", "volume"):
        assert col in df.columns
    assert df["close"].iloc[-1] > 0


def test_cache_hit_is_fast(fmp):
    end = date.today() - timedelta(days=10)
    start = end - timedelta(days=30)
    # First call: populates cache
    fmp.get_historical_prices("MSFT", start, end)
    # Second call: should hit cache
    t0 = time.monotonic()
    df = fmp.get_historical_prices("MSFT", start, end)
    elapsed_ms = (time.monotonic() - t0) * 1000
    assert not df.empty
    assert elapsed_ms < 300, f"cache hit too slow: {elapsed_ms:.0f}ms"


def test_key_metrics_have_roic(fmp):
    km = fmp.get_key_metrics("AAPL", limit=5)
    assert not km.empty
    assert "returnOnInvestedCapital" in km.columns
    assert "filing_date" in km.columns
    # ROIC should be a reasonable number (Apple ROIC ~ 0.3-0.6)
    roic = km["returnOnInvestedCapital"].dropna()
    assert (roic > 0).any()


def test_ratios_have_debt_equity(fmp):
    rt = fmp.get_ratios("AAPL", limit=5)
    assert not rt.empty
    assert "debtToEquityRatio" in rt.columns


def test_sp500_constituents(fmp):
    sp = fmp.get_index_constituents("sp500")
    assert isinstance(sp, list)
    assert len(sp) >= 400
    assert "AAPL" in sp


def test_ftse100_constituents(fmp):
    ftse = fmp.get_ftse100_constituents()
    assert isinstance(ftse, list)
    assert len(ftse) >= 50
    # All should end in .L
    assert all(s.endswith(".L") for s in ftse)


def test_treasury_rates(fmp):
    tr = fmp.get_treasury_rates(date.today() - timedelta(days=30), date.today())
    assert not tr.empty
    assert any(col.startswith("year") for col in tr.columns)


def test_rate_limit_no_429_on_20_calls(fmp):
    """Sanity: 20 prices calls in a row should not 429 (cache mostly hits)."""
    end = date.today() - timedelta(days=15)
    start = end - timedelta(days=20)
    syms = ["AAPL", "MSFT", "GOOG", "META", "AMZN"]
    # Warm cache
    fmp.get_historical_prices_batch(syms, start, end, progress=False)
    # Repeat — should be all cache hits
    for _ in range(20):
        for s in syms:
            fmp.get_historical_prices(s, start, end)
    # If we got here without an exception, rate limiter behaved.
    assert True
