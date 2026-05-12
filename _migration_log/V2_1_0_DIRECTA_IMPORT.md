# v2.1.0 — Directa XLSX importer + reconciliation + gap analysis

## Why

Manual position entry was the single biggest pain point of v2.0.x: every
bond / ETF had to be retyped with ISIN, quantity, price, date, coupon, …
For an investor with 10–20 positions that's tedious **and** error-prone
(see v2.0.1 hotfix, where duplicate-ISIN inserts inflated the bond
sleeve total by ~10× before the duplicate guard was added).

Directa already exports a standard XLSX that contains every position
the broker holds. Parsing that file eliminates ~80 % of manual entry.

## Alternatives considered

| Option | Verdict |
|---|---|
| Directa REST API | ❌ Premium, not available for retail accounts. |
| Web scraping the Directa UI | ❌ ToS violation, 2FA breaks it, security risk. |
| **XLSX import** | ✅ ToS-compliant, robust, manual but only ~30 seconds. |
| OFX / QIF | ❌ Directa doesn't expose either format. |

## Architecture

```
core/data/importers/directa_xlsx.py
    DirectaXLSXImporter        — parser (header row 7, totals dropped)
    DirectaPosition            — one row
    DirectaPortfolioSnapshot   — full snapshot + cash + helpers
    _classify                  — heuristic asset-class tagging
    _extract_issuer            — issuer name from bond name

portfolio/reconciliation.py
    reconcile(snapshot, tracker) → ReconciliationReport
    apply_deltas(report, tracker, user_choices)

ui/utils/gap_analysis.py
    show_gap_analysis(snapshot)
    show_snapshot_summary(snapshot)

ui/pages/3_Aggiorna_Posizioni.py
    new tab "📤 Import da Broker (XLSX)"
```

Reconciliation is broker-agnostic: it diffs by ISIN. Any future importer
(Fineco CSV, IBKR XML, Trade Republic JSON, …) that yields a
``DirectaPortfolioSnapshot``-shaped object plugs in unchanged.

## Limitations

- **Cash balance** is not in the XLSX. The user types it in after
  upload — Directa shows it in the "Situazione patrimonio" panel.
- **Purchase date** is not in the XLSX either. Newly imported positions
  use today's date; this loses historical cost-basis dating but not the
  cost basis itself (`Prezzo medio` is exported).
- **Asset classification is heuristic** (pattern matching on instrument
  name + ISIN prefix + Directa ticker shape). On the reference fixture
  it classifies 12/12 correctly with zero unknowns, but edge cases
  (e.g. a non-standard ETF naming) may fall through to "unknown" —
  the UI flags those in an expander so the user can act manually.
- **Currency conversion** is implicit: Directa reports `Valore di carico`
  and `Valore attuale` already in EUR (their internal FX), so we trust
  those columns for the gap-analysis math. The `Divisa` column is kept
  on each row for transparency.

## Reference run

Tested against the user's real `P_TOTALE_41141_20260512.xlsx`:

| Aggregate | Value |
|---|---:|
| Account | 41141 (MORICONI GIUSEPPE) |
| Extraction date | 2026-05-12 14:32:48 |
| Total portfolio (XLSX) | €169,738.86 |
| Cash (manual input) | €34,877.00 |
| Patrimony total | €204,615.86 |
| Positions | 12 |
| Classified bond | 10 (€166,438) |
| Classified equity | 2 (€2,078) |
| Unknown | 0 |

All 12 positions classified without ambiguity (TELECOM ITALIA, BTP TF /
FX / VALORE, ROMANIA, CARRARO FINANCE, USA TF → bond; APPLE / PAYPAL →
equity).

## Multi-broker future

The pattern of "parser → reconciliation → apply through tracker" is
intentionally tiny:

```
ui_tab → importer.parse(file) → reconcile(snapshot, tracker) → apply_deltas(...)
```

Adding a Fineco CSV importer is essentially: subclass / clone
`DirectaXLSXImporter`, map columns, return a `DirectaPortfolioSnapshot`
(or rename that to `BrokerPortfolioSnapshot`). No UI rewiring needed.
