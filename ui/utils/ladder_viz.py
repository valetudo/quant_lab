"""Storytelling-first visualizations for the Bond Ladder Builder.

Two complementary charts comprehensible to a non-technical reader in 30s:

1. :func:`build_ladder_chart` — a literal ladder. Each rung is a horizontal
   bar drawn at its target maturity date. The bar is split into colored
   segments by category (BTP / corporate / foreign sovereign) sized
   proportionally to the capital allocated to each.

2. :func:`build_cashflow_timeline` — when do the cash inflows arrive?
   Coupons are small grey dots; maturities are big green dots labelled
   with the redemption amount. A floating annotation highlights the
   12-month aggregate expected cash.

Both functions take a :class:`strategies.bonds_income.ladder_builder.LadderProposal`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import plotly.graph_objects as go

if TYPE_CHECKING:
    from strategies.bonds_income.ladder_builder import LadderProposal


_CATEGORY_COLORS = {
    "gov_ita": "#2E7D32",  # green
    "corp": "#F57C00",  # warm orange
    "gov_foreign": "#1565C0",  # deep blue
}

_CATEGORY_LABELS_IT = {
    "gov_ita": "BTP italiani",
    "corp": "Obbligazioni aziendali",
    "gov_foreign": "Titoli di stato esteri",
}

# Theme-neutral text/grid colors. Streamlit can render with either a
# light or a dark theme; choosing mid-grey + transparent backgrounds
# keeps every label readable in both, at the cost of slightly washed-out
# contrast on either extreme. The user-visible labels are the priority.
_LABEL_COLOR = "#888888"
_GRID_COLOR = "rgba(128,128,128,0.25)"
_AXIS_COLOR = "#888888"


def build_ladder_chart(proposal: "LadderProposal") -> go.Figure:
    """Horizontal ladder visualization.

    X axis = time (calendar dates). Y axis = rung index (1 at bottom, N at
    top). Each rung is a horizontal segmented bar within the tolerance
    window; segments correspond to the capital allocated to BTP, corporate,
    foreign sovereign respectively.
    """
    fig = go.Figure()
    today = pd.Timestamp.today().normalize()

    if not proposal.rungs:
        fig.update_layout(title="(nessun gradino)")
        return fig

    tolerance_days = proposal.config.maturity_tolerance_months * 30.4375

    for rung in proposal.rungs:
        y = rung.rung_index + 1
        target = rung.target_maturity_date
        window_start = target - pd.Timedelta(days=tolerance_days)
        window_end = target + pd.Timedelta(days=tolerance_days)
        rung_total = rung.actual_amount_eur

        # If a rung allocated nothing, draw a faint "empty" shape so the
        # ladder still has a visible step at this height.
        if rung_total <= 0:
            fig.add_shape(
                type="rect",
                x0=window_start,
                x1=window_end,
                y0=y - 0.3,
                y1=y + 0.3,
                fillcolor="rgba(150,150,150,0.10)",
                line=dict(color="rgba(150,150,150,0.4)", width=1, dash="dot"),
                layer="below",
            )
        else:
            cumulative = 0.0
            window_total_days = (window_end - window_start).days
            for category in ("gov_ita", "corp", "gov_foreign"):
                bond = rung.selected_bonds.get(category)
                if bond is None:
                    continue
                segment_days = window_total_days * (bond.amount_eur / rung_total)
                seg_start = window_start + pd.Timedelta(
                    days=window_total_days * (cumulative / rung_total)
                )
                seg_end = seg_start + pd.Timedelta(days=segment_days)
                fig.add_shape(
                    type="rect",
                    x0=seg_start,
                    x1=seg_end,
                    y0=y - 0.4,
                    y1=y + 0.4,
                    fillcolor=_CATEGORY_COLORS[category],
                    line=dict(color="white", width=2),
                    opacity=0.92,
                    layer="below",
                )
                # Invisible scatter point gives a hover tooltip per segment.
                seg_mid = seg_start + pd.Timedelta(days=segment_days / 2)
                fig.add_trace(
                    go.Scatter(
                        x=[seg_mid],
                        y=[y],
                        mode="markers",
                        marker=dict(size=24, color=_CATEGORY_COLORS[category], opacity=0),
                        hovertemplate=(
                            f"<b>Gradino {rung.rung_index + 1}</b><br>"
                            f"Scadenza prevista: {bond.maturity_date.strftime('%b %Y')}<br>"
                            f"<br><b>{_CATEGORY_LABELS_IT[category]}</b><br>"
                            f"{bond.name}<br>"
                            f"ISIN: {bond.isin}<br>"
                            f"Capitale: €{bond.amount_eur:,.0f}<br>"
                            f"Rendimento netto: {bond.ytm_net * 100:.2f}% all'anno<br>"
                            f"Quantità: {bond.quantity} lotti × €{bond.lot_size_eur:.0f}<br>"
                            f"Rating: {bond.rating or 'NR'}"
                            "<extra></extra>"
                        ),
                        showlegend=False,
                    )
                )
                cumulative += bond.amount_eur

        # Inline annotation at the left edge of the rung. Explicit color +
        # transparent background so labels stay legible in both light and
        # dark Streamlit themes.
        adapted_marker = " ⚠️" if rung.composition_was_adapted else ""
        fig.add_annotation(
            x=today,
            y=y,
            text=(
                f"<b>Gradino {rung.rung_index + 1}</b><br>"
                f"{target.year}<br>"
                f"€{rung_total:,.0f}{adapted_marker}"
            ),
            showarrow=False,
            xanchor="right",
            xshift=-12,
            font=dict(size=11, color=_LABEL_COLOR, family="Arial"),
            align="right",
            bgcolor="rgba(0,0,0,0)",
        )

    # Legend entries (shapes don't auto-generate legend items).
    for category in ("gov_ita", "corp", "gov_foreign"):
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="markers",
                marker=dict(size=14, color=_CATEGORY_COLORS[category]),
                name=_CATEGORY_LABELS_IT[category],
            )
        )

    last_target = proposal.rungs[-1].target_maturity_date
    fig.update_layout(
        title=dict(
            text="🪜 La tua scala obbligazionaria",
            font=dict(size=20, color=_LABEL_COLOR),
        ),
        xaxis=dict(
            title=dict(
                text="Scadenza nel tempo →",
                font=dict(color=_LABEL_COLOR),
            ),
            type="date",
            range=[today - pd.Timedelta(days=180), last_target + pd.Timedelta(days=365)],
            showgrid=True,
            gridcolor=_GRID_COLOR,
            color=_AXIS_COLOR,
            tickfont=dict(color=_LABEL_COLOR),
        ),
        yaxis=dict(
            range=[0.4, len(proposal.rungs) + 0.6],
            showticklabels=False,
            showgrid=False,
        ),
        height=max(420, 70 * len(proposal.rungs)),
        paper_bgcolor="rgba(0,0,0,0)",  # transparent → inherits Streamlit theme
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=_LABEL_COLOR),
        hovermode="closest",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5,
            font=dict(color=_LABEL_COLOR),
        ),
        margin=dict(l=120, r=40, t=80, b=40),
    )
    return fig


def build_cashflow_timeline(proposal: "LadderProposal") -> go.Figure:
    """Timeline of future cash events.

    Two layers:
    - Coupons: small grey dots (frequent, small amounts).
    - Maturities: large green dots labelled with redemption amount.

    A floating annotation highlights the next-12-months aggregate.
    """
    fig = go.Figure()
    today = pd.Timestamp.today().normalize()

    events: list[dict] = []
    for rung in proposal.rungs:
        for bond in rung.selected_bonds.values():
            if bond is None:
                continue
            face_total = bond.quantity * bond.lot_size_eur
            if bond.coupon_frequency <= 0:
                continue
            coupon_payment = face_total * bond.coupon_rate / bond.coupon_frequency
            step = pd.DateOffset(months=int(12 // bond.coupon_frequency))
            # Walk coupon dates backwards from maturity.
            current = bond.maturity_date
            seen = 0
            while current > today and seen < 60:
                if coupon_payment > 0:
                    events.append(
                        {
                            "date": current,
                            "amount": coupon_payment,
                            "type": "coupon",
                            "bond_name": bond.name,
                            "isin": bond.isin,
                        }
                    )
                current = current - step
                seen += 1
            # Maturity event = capital repayment (the coupon at maturity is
            # already counted in the loop above).
            events.append(
                {
                    "date": bond.maturity_date,
                    "amount": face_total,
                    "type": "maturity",
                    "bond_name": bond.name,
                    "isin": bond.isin,
                }
            )

    if not events:
        fig.update_layout(title="(nessun evento cash)")
        return fig

    coupons = [e for e in events if e["type"] == "coupon"]
    maturities = [e for e in events if e["type"] == "maturity"]

    timeline_end = max(e["date"] for e in events)
    # Spine
    fig.add_shape(
        type="line",
        x0=today,
        x1=timeline_end + pd.Timedelta(days=30),
        y0=1.5,
        y1=1.5,
        line=dict(color="rgba(100,100,100,0.3)", width=2),
    )

    if coupons:
        fig.add_trace(
            go.Scatter(
                x=[e["date"] for e in coupons],
                y=[1] * len(coupons),
                mode="markers",
                marker=dict(size=9, color="#90A4AE", symbol="circle"),
                name="Cedole",
                hovertemplate=(
                    "<b>Cedola</b><br>"
                    "Data: %{x|%b %Y}<br>"
                    "Importo: €%{customdata[0]:,.0f}<br>"
                    "%{customdata[1]}"
                    "<extra></extra>"
                ),
                customdata=[(e["amount"], e["bond_name"]) for e in coupons],
            )
        )

    if maturities:
        fig.add_trace(
            go.Scatter(
                x=[e["date"] for e in maturities],
                y=[2] * len(maturities),
                mode="markers+text",
                marker=dict(size=26, color="#1B5E20", symbol="circle"),
                text=[f"€{e['amount'] / 1000:.0f}k" for e in maturities],
                textposition="top center",
                textfont=dict(size=11, color="black"),
                name="Rimborso capitale",
                hovertemplate=(
                    "<b>Rimborso capitale</b><br>"
                    "Data: %{x|%b %Y}<br>"
                    "Importo: €%{customdata[0]:,.0f}<br>"
                    "%{customdata[1]}"
                    "<extra></extra>"
                ),
                customdata=[(e["amount"], e["bond_name"]) for e in maturities],
            )
        )

    cutoff_12m = today + pd.DateOffset(months=12)
    cash_12m = sum(e["amount"] for e in events if today < e["date"] <= cutoff_12m)
    fig.add_annotation(
        x=today + pd.DateOffset(months=6),
        y=2.85,
        text=(
            f"<b>Prossimi 12 mesi</b><br>"
            f"€{cash_12m:,.0f} di cash atteso"
        ),
        showarrow=False,
        bgcolor="rgba(46, 125, 50, 0.10)",
        bordercolor="#2E7D32",
        borderwidth=1,
        font=dict(size=12, color=_LABEL_COLOR),
    )

    fig.update_layout(
        title=dict(
            text="💰 Quando arrivano i soldi",
            font=dict(size=18, color=_LABEL_COLOR),
        ),
        xaxis=dict(
            title="",
            type="date",
            showgrid=True,
            gridcolor=_GRID_COLOR,
            color=_AXIS_COLOR,
            tickfont=dict(color=_LABEL_COLOR),
        ),
        yaxis=dict(
            range=[0.4, 3.4],
            showticklabels=False,
            showgrid=False,
            zeroline=False,
        ),
        height=320,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=_LABEL_COLOR),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.2,
            xanchor="center",
            x=0.5,
            font=dict(color=_LABEL_COLOR),
        ),
        margin=dict(l=40, r=40, t=80, b=60),
    )
    return fig
