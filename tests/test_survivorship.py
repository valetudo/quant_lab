"""Tests for the Phase-S survivorship-correction plumbing.

These tests use the real FMP cache (the membership history is already
populated by the audit). They make no live API calls — every read goes
through the local DuckDB. If the cache is missing, the tests skip.
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.data.providers.fmp_provider import FMPProvider
from core.data.universe import Universe


@pytest.fixture(scope="module")
def fmp() -> FMPProvider:
    p = FMPProvider()
    # The audit must have populated the membership history table — skip if not
    events = p.get_historical_index_constituents("sp500")
    if events.empty:
        pytest.skip(
            "index_membership_history table is empty — run "
            "scripts/audit_constituent_history.py first"
        )
    return p


def test_today_matches_current(fmp: FMPProvider) -> None:
    current = set(fmp.get_index_constituents("sp500"))
    today = set(fmp.get_constituents_at_date("sp500", pd.Timestamp.today()))
    assert today == current


def test_universe_point_in_time_smaller_overlap_with_current(fmp: FMPProvider) -> None:
    """The farther back we go, the less overlap with today's S&P 500."""
    current = set(fmp.get_index_constituents("sp500"))
    overlaps = []
    for ds in ["2024-01-01", "2018-01-01", "2010-01-01"]:
        u = set(fmp.get_constituents_at_date("sp500", pd.Timestamp(ds)))
        overlaps.append((ds, len(u & current) / len(u)))
    # Monotonic: more recent ⇒ higher overlap with today
    assert overlaps[0][1] > overlaps[1][1] > overlaps[2][1]
    # 2010 overlap should be well below 80%
    assert overlaps[2][1] < 0.80


def test_universe_size_in_sane_range(fmp: FMPProvider) -> None:
    """S&P 500 has been ~500 names for a long time. Sanity-check any date."""
    for ds in ["2010-01-01", "2015-06-30", "2020-12-31", "2024-06-30"]:
        u = fmp.get_constituents_at_date("sp500", pd.Timestamp(ds))
        assert 480 <= len(u) <= 520, f"{ds}: got {len(u)} tickers"


def test_universe_class_modes(fmp: FMPProvider) -> None:
    cur = Universe("sp500", fmp, mode="current")
    pit = Universe("sp500", fmp, mode="point_in_time")
    cur_list = cur.get_constituents()
    pit_today = pit.get_constituents(pd.Timestamp.today())
    pit_2010 = pit.get_constituents(pd.Timestamp("2010-01-01"))
    # Same provider; current and pit_today should match
    assert set(cur_list) == set(pit_today)
    # 2010 differs
    assert set(pit_2010) != set(cur_list)


def test_universe_class_rejects_bad_mode() -> None:
    with pytest.raises(ValueError):
        Universe("sp500", fmp=None, mode="wat")


# ---- strategy-level integration --------------------------------------------


def test_strategy_excludes_future_constituents(fmp: FMPProvider) -> None:
    """V5 survivorship-aware at 2010 must NOT include any ticker that joined
    the S&P 500 after 2010."""
    # Tickers known to have joined the S&P 500 well after 2010:
    # TSLA joined 2020-12-21, META 2013-12-23, ABNB 2024-09-23
    later_joiners = {"TSLA", "META", "ABNB"}
    u_2010 = set(fmp.get_constituents_at_date("sp500", pd.Timestamp("2010-01-01")))
    assert not (later_joiners & u_2010), (
        f"future joiners leaked into the 2010 universe: {later_joiners & u_2010}"
    )


# test_strategy_survivorship_smoke removed 2026-05-11: QualityStocks was archived
# (see _migration_log/V5_VS_SPY_DECISION.md). The survivorship plumbing it
# exercised — FMPProvider.get_constituents_at_date and the Universe
# point_in_time mode — is still covered by the other tests in this file.
