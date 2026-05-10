"""Provider scaffolding tests — instantiation + ID stability."""
from __future__ import annotations

from quant_lab.core.data.providers.base import BaseProvider
from quant_lab.core.data.providers.borsa_italiana_provider import BorsaItalianaProvider
from quant_lab.core.data.providers.stub_fmp_provider import FMPProvider
from quant_lab.core.data.providers.yfinance_provider import YFinanceProvider


def test_all_providers_subclass_base():
    for cls in (BorsaItalianaProvider, FMPProvider, YFinanceProvider):
        assert issubclass(cls, BaseProvider)


def test_provider_ids():
    assert FMPProvider().provider_id == "fmp"
    assert YFinanceProvider().provider_id == "yfinance"
    assert BorsaItalianaProvider().provider_id == "borsa_italiana"


def test_fmp_stub_safe_calls():
    p = FMPProvider()
    r = p.refresh()
    assert r["status"] == "not_implemented"
    f = p.fetch_fundamentals("AAPL")
    assert f["status"] == "not_implemented"
