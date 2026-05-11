"""Provider scaffolding tests — instantiation + ID stability."""

from __future__ import annotations

import os

import pytest

from core.data.providers.base import BaseProvider
from core.data.providers.borsa_italiana_provider import BorsaItalianaProvider
from core.data.providers.fmp_provider import FMPProvider
from core.data.providers.yfinance_provider import YFinanceProvider


def test_all_providers_subclass_base():
    for cls in (BorsaItalianaProvider, FMPProvider, YFinanceProvider):
        assert issubclass(cls, BaseProvider)


def test_yfinance_provider_id():
    assert YFinanceProvider().provider_id == "yfinance"


def test_borsa_italiana_provider_id():
    assert BorsaItalianaProvider().provider_id == "borsa_italiana"


@pytest.mark.skipif(
    not os.getenv("FMP_API_KEY"),
    reason="FMP_API_KEY not set",
)
def test_fmp_provider_instantiates():
    p = FMPProvider()
    assert p.provider_id == "fmp"
    r = p.refresh()
    assert r["status"] == "ok"
