"""Smoke tests for the Bond Ladder PDF export (`reporting.ladder_pdf`)."""

from __future__ import annotations

from io import BytesIO

import pandas as pd

from reporting.ladder_pdf import _default_borsa_url, generate_ladder_pdf
from strategies.bonds_income.ladder_builder import (
    LadderBuilder,
    LadderBuilderConfig,
)


def _toy_proposal():
    """Build a tiny proposal from a synthetic universe (no bonds.db)."""
    today = pd.Timestamp.today().normalize()
    rows = []
    for years in (1, 2, 3):
        for cat, issuer, isin, yld in (
            ("gov_ita", "Italia", f"IT-{years}", 2.5 + 0.2 * years),
            ("corp", "Eni", f"IT-C-{years}", 2.8 + 0.2 * years),
        ):
            rows.append(
                {
                    "isin": isin,
                    "name": f"{issuer} {years}y",
                    "issuer": issuer,
                    "category": cat,
                    "nation": "Italia",
                    "maturity_date": today + pd.Timedelta(days=int(365.25 * years)),
                    "yield_net": yld / 100,
                    "price_clean": 100.0,
                    "rating": "BBB",
                    "rating_score": 9,
                    "coupon_rate": 0.03,
                    "coupon_frequency": 1,
                    "lot_size_eur": 1000.0,
                    "is_callable": False,
                    "is_subordinated": False,
                    "currency": "EUR",
                }
            )
    universe = pd.DataFrame(rows)
    cfg = LadderBuilderConfig(
        budget_eur=30_000, n_rungs=3, max_duration_years=3
    )
    return LadderBuilder(cfg, universe=universe).build()


def test_generate_pdf_to_bytesio_is_valid_pdf():
    proposal = _toy_proposal()
    buf = BytesIO()
    generate_ladder_pdf(proposal, buf)
    data = buf.getvalue()
    assert data.startswith(b"%PDF-")
    assert data.rstrip().endswith(b"%%EOF")
    assert len(data) > 2000  # a real multi-page document


def test_generate_pdf_to_path(tmp_path):
    proposal = _toy_proposal()
    out = tmp_path / "ladder.pdf"
    generate_ladder_pdf(proposal, out)
    assert out.exists()
    assert out.read_bytes().startswith(b"%PDF-")


def test_pdf_contains_isin_hyperlink_annotations():
    """Every selected bond's ISIN must become a clickable /Link annotation."""
    proposal = _toy_proposal()
    buf = BytesIO()
    generate_ladder_pdf(proposal, buf)
    data = buf.getvalue()
    # ReportLab emits link annotations as "/Subtype /Link" (sometimes
    # compressed). Decompress every stream and count.
    import re
    import zlib

    link_count = data.count(b"/Link")
    for m in re.finditer(rb"stream\r?\n", data):
        chunk = data[m.end() : data.find(b"endstream", m.end())]
        try:
            link_count += zlib.decompress(chunk).count(b"/Link")
        except Exception:
            pass
    assert link_count >= proposal.n_bonds_selected, (
        f"expected ≥{proposal.n_bonds_selected} link annotations, got {link_count}"
    )


def test_default_borsa_url_categorisation():
    btp = _default_borsa_url("IT0005634800", "BTP TF 2.1% LG26")
    assert "/mot/btp/scheda/IT0005634800.html" in btp
    corp = _default_borsa_url("XS2178857954", "ROMANIA TF 3.624% MG30")
    assert "/mot/obbligazioni-euro/scheda/XS2178857954.html" in corp
