"""Small label rendered at the top of pages to signal their purpose.

v3.0.0 split the UI into two modes:

- ``"ricerca"``     — research / decision tools, the primary v3 flow.
- ``"portfolio"``  — portfolio-management pages (hidden from primary nav,
                     still accessible via direct URL).

This helper renders a single colored badge + an optional explainer
caption underneath, so the user immediately knows which kind of page
they landed on.
"""

from __future__ import annotations

from typing import Literal

import streamlit as st

ModeName = Literal["ricerca", "portfolio", "hidden"]


_MODE_STYLES: dict[str, dict[str, str]] = {
    "ricerca": {
        "label": "Modalità ricerca",
        "color_bg": "rgba(21, 101, 192, 0.10)",
        "color_border": "#1565C0",
        "emoji": "🔬",
    },
    "portfolio": {
        "label": "Portfolio management",
        "color_bg": "rgba(46, 125, 50, 0.10)",
        "color_border": "#2E7D32",
        "emoji": "📊",
    },
    "hidden": {
        "label": "Pagina nascosta",
        "color_bg": "rgba(180, 83, 9, 0.10)",
        "color_border": "#B45309",
        "emoji": "🔒",
    },
}


def mode_badge(mode: ModeName, caption: str | None = None) -> None:
    """Render a colored badge + optional caption at the top of a page."""
    style = _MODE_STYLES.get(mode, _MODE_STYLES["ricerca"])
    st.markdown(
        f"""
<div style="
    display:inline-block;
    background:{style['color_bg']};
    border-left:3px solid {style['color_border']};
    padding:4px 12px;
    border-radius:4px;
    font-size:0.85em;
    color:{style['color_border']};
    margin-bottom:8px;
">
{style['emoji']} <b>{style['label']}</b>
</div>
""",
        unsafe_allow_html=True,
    )
    if caption:
        st.caption(caption)
