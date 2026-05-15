# v3.2.0 — kaleido unusable on Windows, native ReportLab chart instead

## What was attempted

The original v3.2.0 plan exported the ladder chart as a Plotly figure →
SVG (via `fig.to_image(format="svg")`, engine = kaleido) → `svglib` →
ReportLab `Drawing`.

## What happened

- `kaleido 1.3.0` (latest) is **API-incompatible with plotly 5.22**:
  plotly's `io/_kaleido.py` looks for `kaleido.scopes.plotly`, which only
  exists in the 0.x line. Result: `ValueError: Image export using the
  "kaleido" engine requires the kaleido package`.
- Downgrading to `kaleido==0.2.1` (the version plotly 5.22 expects)
  installs cleanly but **`fig.to_image()` hangs forever** — verified by
  a 45-second watchdog that had to SIGKILL the process. This is the
  well-documented kaleido-0.2.1-on-Windows Chromium-subprocess bug.

Both SVG and PNG go through kaleido, so the PNG fallback in the original
plan is equally dead.

## Decision

**Render the ladder chart natively with `reportlab.graphics`** —
`Drawing` + `Rect` + `String` primitives. This is strictly better here:

- Zero subprocess, zero Chromium, zero hang risk.
- Native PDF vector quality.
- Full control of the palette (matches the UI green/orange/blue exactly).
- No `kaleido` / `svglib` runtime dependency for the PDF feature.
- Deterministic and fast (< 10 ms).

The ladder chart is geometrically trivial — one horizontal segmented bar
per rung — so re-drawing it with ReportLab primitives is ~60 lines and
faithful to `ui/utils/ladder_viz.build_ladder_chart`.

## Consequences for requirements.txt

- `reportlab` — **added** (required, works perfectly).
- `kaleido` — **NOT added** (hangs on Windows; never imported by the PDF code).
- `svglib` — **NOT added** (only needed for the abandoned SVG route).

`kaleido` / `svglib` happen to be installed in the current dev env from
the investigation, but the PDF module imports neither — a fresh clone
with only `reportlab` works fully.
