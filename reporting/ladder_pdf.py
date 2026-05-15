"""PDF export for a Bond Ladder proposal.

Generates a clean 4-page A4 document:

1. Cover — title, parameters, headline metrics, plain-Italian explanation.
2. Chart — the literal ladder, drawn natively with ReportLab graphics
   primitives (no Plotly/kaleido — see ``_migration_log/v320_kaleido_issue.md``
   for why), plus a colour legend.
3. Table — every selected bond, one row each, with the ISIN as a working
   hyperlink to its Borsa Italiana scheda.
4. Notes — operational steps + disclaimer.

The only hard dependency is ``reportlab``. Typography is Helvetica (a PDF
core font, no install needed). The palette matches the Quant Lab UI.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

log = logging.getLogger(__name__)


# ---------- palette (matches the Quant Lab UI) ----------

COLOR_BTP = colors.HexColor("#2E7D32")
COLOR_CORP = colors.HexColor("#F57C00")
COLOR_FOREIGN = colors.HexColor("#1565C0")
COLOR_HEADER_BG = colors.HexColor("#1E2127")
COLOR_HEADER_TEXT = colors.HexColor("#FFFFFF")
COLOR_BODY_TEXT = colors.HexColor("#212121")
COLOR_TABLE_ROW_ALT = colors.HexColor("#F5F5F5")
COLOR_TABLE_ROW = colors.HexColor("#FFFFFF")
COLOR_MUTED = colors.HexColor("#757575")
COLOR_LINK = colors.HexColor("#1565C0")
COLOR_EMPTY = colors.HexColor("#E0E0E0")

_CATEGORY_COLOR = {
    "gov_ita": COLOR_BTP,
    "corp": COLOR_CORP,
    "gov_foreign": COLOR_FOREIGN,
}
# Plain-text labels — the PDF core font (Helvetica) has no emoji glyphs,
# so flag/building emoji would render as tofu squares. Category colour is
# conveyed by the chart + the colored bullet in each table cell instead.
_CATEGORY_LABEL = {
    "gov_ita": "BTP",
    "corp": "Corporate",
    "gov_foreign": "Gov estero",
}


# ---------- helpers ----------


def _eur(amount: float) -> str:
    """Italian-style euro formatting: thousands dot, no decimals."""
    return "€ " + f"{amount:,.0f}".replace(",", ".")


def _default_borsa_url(isin: str, name: str = "") -> str:
    """Fallback BI scheda URL builder (mirrors the v3.1.5 UI helper)."""
    isin = (isin or "").upper().strip()
    name_upper = (name or "").upper()
    if any(tok in name_upper for tok in ("BTP", "BOT", "CCT", "CTZ")):
        categoria = "btp"
    else:
        categoria = "obbligazioni-euro"
    return (
        f"https://www.borsaitaliana.it/borsa/obbligazioni/mot/"
        f"{categoria}/scheda/{isin}.html?lang=it"
    )


def _build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=28,
            textColor=COLOR_BODY_TEXT,
            spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=12,
            leading=16,
            textColor=COLOR_MUTED,
            spaceAfter=20,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            textColor=COLOR_BODY_TEXT,
            spaceBefore=16,
            spaceAfter=8,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=COLOR_BODY_TEXT,
            spaceAfter=6,
        ),
        "body_just": ParagraphStyle(
            "body_just",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=COLOR_BODY_TEXT,
            spaceAfter=6,
            alignment=4,  # justified
        ),
        "muted": ParagraphStyle(
            "muted",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=9,
            leading=12,
            textColor=COLOR_MUTED,
            spaceAfter=6,
        ),
        "cell": ParagraphStyle(
            "cell",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=COLOR_BODY_TEXT,
        ),
    }


def _page_decorator(generation_date: str) -> Callable:
    """Footer painted on every page: generation date + page number."""

    def _decorate(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(COLOR_MUTED)
        canvas.drawString(2 * cm, 1.2 * cm, f"Generato: {generation_date}")
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Pagina {doc.page}")
        canvas.setStrokeColor(COLOR_EMPTY)
        canvas.setLineWidth(0.5)
        canvas.line(2 * cm, 1.5 * cm, A4[0] - 2 * cm, 1.5 * cm)
        canvas.restoreState()

    return _decorate


# ---------- native ladder chart (ReportLab graphics) ----------


def _build_ladder_chart_drawing(proposal) -> Drawing:
    """Draw the literal ladder as a ReportLab ``Drawing``.

    One horizontal segmented bar per rung, stacked top-to-bottom. Each
    bar's total width is proportional to the rung's allocated capital;
    each coloured segment within it is proportional to the capital in
    that category. Faithful to ``ui.utils.ladder_viz.build_ladder_chart``
    but rendered with native vector primitives — no kaleido.
    """
    rungs = list(proposal.rungs)
    n = max(1, len(rungs))

    width = 17 * cm
    row_h = 30
    pad_left = 135
    pad_right = 70
    pad_top = 10
    pad_bottom = 10
    bar_area_w = width - pad_left - pad_right
    height = pad_top + pad_bottom + n * row_h

    d = Drawing(width, height)
    max_amt = max((r.actual_amount_eur for r in rungs), default=1.0) or 1.0

    for i, rung in enumerate(rungs):
        # Rung 0 at the top.
        row_top = height - pad_top - i * row_h
        bar_h = row_h - 12
        bar_y = row_top - row_h + 6

        # Left-side label.
        d.add(
            String(
                6,
                bar_y + bar_h / 2 - 3,
                f"Gradino {rung.rung_index + 1}  ·  "
                f"{rung.target_maturity_date.year}",
                fontName="Helvetica",
                fontSize=8,
                fillColor=COLOR_BODY_TEXT,
            )
        )

        rung_total = rung.actual_amount_eur
        if rung_total <= 0:
            # Empty rung — faint placeholder so the ladder still has a step.
            d.add(
                Rect(
                    pad_left,
                    bar_y,
                    34,
                    bar_h,
                    fillColor=COLOR_EMPTY,
                    strokeColor=COLOR_MUTED,
                    strokeWidth=0.5,
                )
            )
            d.add(
                String(
                    pad_left + 40,
                    bar_y + bar_h / 2 - 3,
                    "vuoto",
                    fontName="Helvetica-Oblique",
                    fontSize=7,
                    fillColor=COLOR_MUTED,
                )
            )
            continue

        bar_w = bar_area_w * (rung_total / max_amt)
        x = pad_left
        for cat in ("gov_ita", "corp", "gov_foreign"):
            bond = rung.selected_bonds.get(cat)
            if bond is None:
                continue
            seg_w = bar_w * (bond.amount_eur / rung_total)
            if seg_w <= 0:
                continue
            d.add(
                Rect(
                    x,
                    bar_y,
                    seg_w,
                    bar_h,
                    fillColor=_CATEGORY_COLOR[cat],
                    strokeColor=colors.white,
                    strokeWidth=0.6,
                )
            )
            x += seg_w

        # Amount label at the end of the bar.
        d.add(
            String(
                pad_left + bar_w + 5,
                bar_y + bar_h / 2 - 3,
                _eur(rung_total),
                fontName="Helvetica",
                fontSize=7,
                fillColor=COLOR_MUTED,
            )
        )

    return d


# ---------- page builders ----------


def _cover_page(proposal, styles, generation_date: str) -> list:
    el: list = []
    el.append(Paragraph("Bond Ladder Proposal", styles["title"]))
    el.append(Paragraph(f"Generato il {generation_date}", styles["subtitle"]))

    cfg = proposal.config
    meta = [
        ["Budget totale:", _eur(cfg.budget_eur)],
        ["Numero di gradini:", str(cfg.n_rungs)],
        ["Duration massima:", f"{cfg.max_duration_years} anni"],
        [
            "Composizione target:",
            f"{cfg.gov_ita_weight * 100:.0f}% BTP / "
            f"{cfg.corp_weight * 100:.0f}% Corporate / "
            f"{cfg.gov_foreign_weight * 100:.0f}% Gov estero",
        ],
    ]
    meta_t = Table(meta, colWidths=[5 * cm, 12 * cm])
    meta_t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TEXTCOLOR", (0, 0), (0, -1), COLOR_MUTED),
                ("TEXTCOLOR", (1, 0), (1, -1), COLOR_BODY_TEXT),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    el.append(meta_t)
    el.append(Spacer(1, 18))

    coverage = (
        proposal.total_allocated_eur / cfg.budget_eur * 100
        if cfg.budget_eur > 0
        else 0.0
    )
    metrics = [
        ["Capitale allocato", "Rendimento medio", "Numero bond", "Coverage"],
        [
            _eur(proposal.total_allocated_eur),
            f"{proposal.weighted_avg_ytm * 100:.2f}%",
            str(proposal.n_bonds_selected),
            f"{coverage:.1f}%",
        ],
    ]
    metrics_t = Table(metrics, colWidths=[4.25 * cm] * 4)
    metrics_t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), COLOR_HEADER_BG),
                ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_HEADER_TEXT),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, 0), 7),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
                ("BACKGROUND", (0, 1), (-1, 1), COLOR_TABLE_ROW_ALT),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 1), (-1, 1), 15),
                ("TEXTCOLOR", (0, 1), (-1, 1), COLOR_BODY_TEXT),
                ("TOPPADDING", (0, 1), (-1, 1), 11),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 11),
            ]
        )
    )
    el.append(metrics_t)
    el.append(Spacer(1, 22))

    el.append(Paragraph("Cos'è un bond ladder?", styles["h2"]))
    el.append(
        Paragraph(
            "Un <b>bond ladder</b> (scala obbligazionaria) distribuisce il "
            "capitale su obbligazioni con scadenze diverse, così da ricevere "
            "il capitale indietro a intervalli regolari invece di tutto in una "
            "volta sola. Ogni anno (o quasi) ne scade uno, e i soldi rimborsati "
            "possono essere reinvestiti in un nuovo bond a scadenza lunga — la "
            "scala si rinnova continuamente.",
            styles["body_just"],
        )
    )
    el.append(
        Paragraph(
            "Questa proposta è stata generata automaticamente dal Ladder "
            "Builder di Quant Lab, selezionando bond dal catalogo Borsa "
            "Italiana che rispettano la composizione target richiesta e i "
            "filtri qualitativi (rating, no callable, no subordinati).",
            styles["body_just"],
        )
    )
    el.append(Spacer(1, 8))

    el.append(Paragraph("Come leggere questo documento", styles["h2"]))
    el.append(
        Paragraph(
            "<b>Pagina 2</b> — visualizzazione grafica della ladder: ogni "
            "barra è un gradino (una scadenza), i colori indicano la categoria "
            "del bond.",
            styles["body_just"],
        )
    )
    el.append(
        Paragraph(
            "<b>Pagina 3</b> — tabella dettagliata dei bond. Ogni ISIN è "
            "cliccabile e apre la scheda ufficiale di Borsa Italiana.",
            styles["body_just"],
        )
    )
    el.append(
        Paragraph(
            "<b>Pagina 4</b> — note operative per eseguire gli ordini al "
            "broker e disclaimer.",
            styles["body_just"],
        )
    )
    return el


def _chart_page(proposal, styles) -> list:
    el: list = []
    el.append(Paragraph("Visualizzazione della Ladder", styles["h2"]))
    el.append(
        Paragraph(
            "Ogni barra rappresenta un gradino della scala. La larghezza è "
            "proporzionale al capitale allocato; i segmenti colorati mostrano "
            "la composizione per categoria.",
            styles["muted"],
        )
    )
    el.append(Spacer(1, 10))
    try:
        el.append(_build_ladder_chart_drawing(proposal))
    except Exception as e:  # pragma: no cover - defensive
        log.warning("ladder chart drawing failed: %s", e)
        el.append(
            Paragraph(
                "<i>(Grafico non disponibile — vedi la tabella a pagina 3.)</i>",
                styles["muted"],
            )
        )
    el.append(Spacer(1, 18))

    el.append(Paragraph("Legenda colori", styles["h2"]))

    def _swatch(fill) -> Drawing:
        """A small filled square — drawn as a vector Rect, not a glyph, so
        the PDF never references the (un-embedded) Symbol font."""
        d = Drawing(14, 12)
        d.add(Rect(0, 1, 12, 10, fillColor=fill, strokeColor=fill))
        return d

    legend = [
        [
            _swatch(COLOR_BTP),
            "BTP italiani",
            "Titoli di stato italiani — massima sicurezza, garanzia statale.",
        ],
        [
            _swatch(COLOR_CORP),
            "Obbligazioni aziendali",
            "Corporate investment grade — rendimento superiore, rischio credito.",
        ],
        [
            _swatch(COLOR_FOREIGN),
            "Titoli di stato esteri",
            "Gov estero in EUR — diversificazione geografica.",
        ],
    ]
    legend_t = Table(legend, colWidths=[0.8 * cm, 4.8 * cm, 11 * cm])
    legend_t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (1, 0), (1, -1), 10),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica"),
                ("FONTSIZE", (2, 0), (2, -1), 9),
                ("TEXTCOLOR", (1, 0), (-1, -1), COLOR_BODY_TEXT),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    el.append(legend_t)
    return el


def _table_page(proposal, styles, url_fn: Callable[[str, str], str]) -> list:
    el: list = []
    el.append(Paragraph("Bond selezionati", styles["h2"]))
    el.append(
        Paragraph(
            "Ogni ISIN è cliccabile e apre la pagina ufficiale di Borsa "
            "Italiana con prezzi, scheda e prospetto.",
            styles["muted"],
        )
    )
    el.append(Spacer(1, 10))

    header = ["Gradino", "Bond", "ISIN", "Capitale", "YTM", "Scadenza"]
    rows: list = [header]
    for rung in proposal.rungs:
        for category, bond in rung.selected_bonds.items():
            if bond is None:
                continue
            url = url_fn(bond.isin, bond.name)
            isin_cell = Paragraph(
                f'<link href="{url}" color="#1565C0"><u>{bond.isin}</u></link>',
                styles["cell"],
            )
            cat_hex = {
                "gov_ita": "#2E7D32",
                "corp": "#F57C00",
                "gov_foreign": "#1565C0",
            }.get(category, "#757575")
            # Category conveyed by the label's text colour — no Symbol-font
            # bullet glyph (it isn't embedded and breaks portability).
            name_cell = Paragraph(
                f"<b>{bond.name}</b><br/>"
                f'<font size="7" color="{cat_hex}"><b>'
                f"{_CATEGORY_LABEL.get(category, category)}</b></font>",
                styles["cell"],
            )
            maturity = (
                bond.maturity_date.strftime("%d/%m/%Y")
                if bond.maturity_date is not None
                else "—"
            )
            rows.append(
                [
                    str(rung.rung_index + 1),
                    name_cell,
                    isin_cell,
                    _eur(bond.amount_eur),
                    f"{bond.ytm_net * 100:.2f}%",
                    maturity,
                ]
            )

    col_widths = [1.6 * cm, 5.6 * cm, 3.4 * cm, 2.6 * cm, 1.7 * cm, 2.1 * cm]
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_HEADER_TEXT),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("ALIGN", (3, 1), (4, -1), "RIGHT"),
        ("ALIGN", (5, 1), (5, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, COLOR_MUTED),
    ]
    for i in range(1, len(rows)):
        bg = COLOR_TABLE_ROW_ALT if i % 2 == 1 else COLOR_TABLE_ROW
        style_cmds.append(("BACKGROUND", (0, i), (-1, i), bg))
    table.setStyle(TableStyle(style_cmds))
    el.append(table)

    if len(rows) == 1:
        el.append(Spacer(1, 8))
        el.append(
            Paragraph("Nessun bond selezionato in questa proposta.", styles["muted"])
        )
    return el


def _notes_page(styles) -> list:
    el: list = []
    el.append(Paragraph("Note operative", styles["h2"]))
    el.append(
        Paragraph(
            "Questa proposta è una <b>indicazione di acquisto</b>, non un "
            "ordine. Per realizzare la ladder:",
            styles["body_just"],
        )
    )
    steps = [
        "<b>1. Verifica i prezzi attuali</b> dei bond sul tuo broker. I prezzi "
        "della proposta sono allo snapshot in cache e possono essere cambiati.",
        "<b>2. Esegui gli ordini</b> uno per uno sul broker (Directa, Fineco, "
        "IBKR). Inserisci ISIN, quantità in nominale (€) e prezzo limite.",
        "<b>3. Verifica l'eseguito</b>: prendi nota dei prezzi effettivi — "
        "possono differire dalla proposta per spread bid/ask e oscillazioni "
        "intraday.",
        "<b>4. Conserva la documentazione</b> dell'eseguito del broker. "
        "L'integrazione automatica via API broker arriverà in futuro.",
        "<b>5. Reinvesti alla scadenza</b>: ogni anno, quando un bond scade, "
        "usa il Ladder Builder per reinvestire il capitale rimborsato in un "
        "nuovo bond a scadenza lunga, mantenendo viva la scala.",
    ]
    for s in steps:
        el.append(Paragraph(s, styles["body_just"]))
        el.append(Spacer(1, 4))
    el.append(Spacer(1, 18))

    el.append(Paragraph("Disclaimer", styles["h2"]))
    el.append(
        Paragraph(
            "<b>Questo documento non costituisce consulenza finanziaria.</b> "
            "È una proposta tecnica generata automaticamente da un sistema di "
            "supporto alle decisioni, basata su parametri inseriti dall'utente "
            "e dati di mercato disponibili. Le decisioni di investimento sono "
            "responsabilità esclusiva dell'utente.",
            styles["body_just"],
        )
    )
    el.append(
        Paragraph(
            "I rendimenti indicati (YTM) sono <b>stime al momento della "
            "generazione</b>, basate sui prezzi più recenti in cache, e possono "
            "differire dai rendimenti effettivamente realizzati. I bond "
            "comportano rischio di credito, rischio tasso e rischio liquidità.",
            styles["body_just"],
        )
    )
    el.append(
        Paragraph(
            "I link a Borsa Italiana sono forniti per facilitare la "
            "consultazione della scheda ufficiale. Quant Lab non è affiliato a "
            "Borsa Italiana.",
            styles["body_just"],
        )
    )
    return el


# ---------- public API ----------


def generate_ladder_pdf(
    proposal,
    output,
    *,
    build_borsa_url_fn: Optional[Callable[[str, str], str]] = None,
) -> None:
    """Render ``proposal`` to a PDF.

    Args:
        proposal: a ``LadderProposal``.
        output: a filesystem path (str / Path) or a writable binary
            file-like object (e.g. ``io.BytesIO``).
        build_borsa_url_fn: ``callable(isin, name) -> url`` for the ISIN
            hyperlinks. Defaults to :func:`_default_borsa_url`.
    """
    url_fn = build_borsa_url_fn or _default_borsa_url
    styles = _build_styles()
    generation_date = datetime.now().strftime("%d/%m/%Y %H:%M")

    target = str(output) if isinstance(output, (str, Path)) else output
    doc = SimpleDocTemplate(
        target,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="Bond Ladder Proposal",
        author="Quant Lab",
    )

    story: list = []
    story.extend(_cover_page(proposal, styles, generation_date))
    story.append(PageBreak())
    story.extend(_chart_page(proposal, styles))
    story.append(PageBreak())
    story.extend(_table_page(proposal, styles, url_fn))
    story.append(PageBreak())
    story.extend(_notes_page(styles))

    decorator = _page_decorator(generation_date)
    doc.build(story, onFirstPage=decorator, onLaterPages=decorator)
