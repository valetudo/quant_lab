# v3.2.0 — Export PDF Bond Ladder

## Feature

Pulsante **📄 Esporta PDF** nella pagina Ladder Builder (sezione
"📤 Esporta proposta", accanto a Esporta CSV). Genera un PDF A4
formattato di 4–5 pagine della proposta corrente:

1. **Cover** — titolo, parametri (budget / gradini / duration /
   composizione target), striscia metriche (capitale allocato,
   rendimento medio, n° bond, coverage), spiegazione "cos'è un bond
   ladder" + "come leggere il documento".
2. **Grafico** — la ladder come barre orizzontali segmentate, una per
   gradino, colorate per categoria + legenda.
3. **Tabella** — un bond per riga: Gradino, Bond, ISIN (hyperlink
   cliccabile), Capitale, YTM, Scadenza. Zebra stripes, header scuro.
   Spilla su pagina successiva se i bond sono molti.
4. **Note** — passi operativi per eseguire gli ordini + disclaimer.

Nome file: `bond_ladder_YYYY-MM-DD.{pdf,csv}`.

## Stack tecnico — e perché NON Plotly/kaleido

Lo spec originale prevedeva: grafico Plotly → SVG (kaleido) → svglib →
ReportLab. **Su Windows kaleido è inutilizzabile**:

- `kaleido 1.3.0` è API-incompatibile con `plotly 5.22` (plotly cerca
  `kaleido.scopes.plotly`, esistente solo nella linea 0.x).
- `kaleido 0.2.1` (la versione attesa da plotly 5.22) installa ma
  `fig.to_image()` **si blocca all'infinito** — verificato con un
  watchdog di 45 s che ha dovuto SIGKILL il processo. Bug noto del
  subprocess Chromium di kaleido su Windows. Sia SVG che PNG passano da
  kaleido, quindi anche il fallback PNG dello spec è morto.

**Decisione**: il grafico ladder è disegnato **nativamente con
`reportlab.graphics`** (`Drawing` + `Rect` + `String`). È strettamente
meglio qui:

- Zero subprocess, zero Chromium, zero rischio di hang.
- Qualità vettoriale nativa PDF.
- Controllo totale della palette (match esatto con la UI).
- Nessuna dipendenza runtime da kaleido / svglib.
- Deterministico e veloce (< 10 ms).

Dettaglio completo in `_migration_log/v320_kaleido_issue.md`.

Unica dipendenza nuova in `requirements.txt`: **`reportlab==4.5.1`**.

## File creati / modificati

| File | Tipo |
|---|---|
| `reporting/__init__.py` | nuovo (package) |
| `reporting/ladder_pdf.py` | nuovo (~480 righe) |
| `ui/pages/13_Ladder_Builder.py` | esteso (sezione "📤 Esporta proposta") |
| `tests/test_ladder_pdf.py` | nuovo (4 test) |
| `requirements.txt` | + reportlab |

## Note di implementazione

- **Niente glifi esotici**: la prima bozza usava `■`/`●` per i bullet di
  categoria. Quei caratteri (U+25A0 / U+25CF) fanno sì che ReportLab
  riferisca il font *Symbol*, che non viene embeddato — pagine
  illeggibili su renderer privi di Symbol. Sostituiti con: (a) etichette
  di categoria a testo colorato nella tabella, (b) veri `Rect` vettoriali
  come swatch nella legenda. Il PDF finale usa solo font core-14
  (Helvetica + Times-Roman) — verificato decomprimendo tutti gli stream.
- **Hyperlink ISIN**: `<link href="...">` dentro un `Paragraph`; ReportLab
  emette annotazioni PDF `/Link` native, funzionanti in ogni reader. URL
  costruito con il pattern v3.1.5 (`/borsa/obbligazioni/mot/<cat>/scheda/<ISIN>.html`).
- **Output flessibile**: `generate_ladder_pdf(proposal, output)` accetta
  sia un path sia un file-like (`BytesIO`) — la UI usa `BytesIO` per
  alimentare direttamente `st.download_button` (single-click download).

## Test

`tests/test_ladder_pdf.py` (4 nuovi):
- PDF valido (header `%PDF-`, trailer `%%EOF`) verso BytesIO.
- PDF valido verso un path.
- ≥ N annotazioni `/Link` (una per bond selezionato).
- Categorizzazione URL Borsa Italiana (btp vs obbligazioni-euro).

Suite: 102 → **106**, 0 regressioni.

## Verifica visiva

Generato con budget €50k / 10 gradini / 10y (23 bond): 5 pagine,
chart nativo corretto, legenda con swatch colorati, tabella zebra con
23 hyperlink ISIN cliccabili. Tutte le pagine renderizzate pulite.

## Backward compatibility

100%: nuovo modulo `reporting/`, nessuna API esistente toccata, backend
ladder builder invariato.
