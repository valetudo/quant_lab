# v3.1.1 — Ladder Builder refinements

## Feedback utente

Tre richieste dopo uso reale del Ladder Builder in v3.1.0:

> 1. *"Cosa vuol dire 'Concentrazioni emittenti oltre il limite: Obligaciones Fx: 5.3% > limite 5%'?"*
> 2. *"Vorrei priorità all'allocazione totale dei fondi, se per ottenerla si sacrifica leggermente il rendimento mi va bene. Mettiamo un log."*
> 3. *"Quando il mouse passa sopra i rettangoli dei gradini di una ladder, voglio poter cliccare sul bond e che mi mandi alla pagina Borsa Italiana di quel bond."*

## Cambiamenti

### 1. Concentration-limit warning chiarito (Task 1)

Il banner generico è stato sostituito con un container bordato che spiega:

- **Cos'è il limite**: 5 % del budget per singolo emittente corporate.
- **Perché esiste**: rischio credito → perdere 5 % è doloroso ma gestibile,
  perdere 15 % è catastrofico.
- **Quanto è grave lo sforamento**: ogni issuer è classificato "minimo"
  (< 2 pp) o "significativo" (≥ 2 pp).
- **Cosa fare**: suggerimento dipendente dalla severità — info banner verde
  per minimi, warning arancione per significativi.

Tooltip `ℹ️` con razionale esteso per chi vuole approfondire.

Modalità **tolerant** confermata: il builder accetta lo sforamento, mostra
il warning, l'utente decide se ribilanciare manualmente o accettare.

### 2. Toggle "Massimizza allocazione" (Task 2)

Nuovo campo `LadderBuilderConfig.maximize_allocation` (default `False`).

Quando `True`, dopo lo standard pass il builder applica due strategie
sequenziali:

**Step A — Tolerance window expansion**:
Per ogni rung con `coverage_pct < 0.9` riesegue `_build_rung` con tolerance
±12 → ±18 → ±24 mesi (cap configurabile in `max_tolerance_months`,
default 24). Il `global_alloc` per la concentration cap viene
ricalcolato escludendo la rung in fase di rebuild così non c'è double-count.

**Step B — Greedy reallocation**:
Se dopo Step A resta più del `min_residue_threshold_pct` (default 5 %)
non allocato, il builder pesca iterativamente la rung col fill rate più
alto e ci aggiunge un lotto extra del bond più economico che ci sta dentro
del residuo + la concentration cap. Loop con safety cap 50 iterazioni.

**Telemetria**:
- `LadderProposal.allocation_log: list[str]` — sempre popolata, anche con
  maximize OFF (Step 1 + 4 righe di summary).
- `LadderProposal.yield_without_maximization: Optional[float]` — set
  quando il maximize ON ha cambiato il rendimento medio rispetto allo
  standard pass.

### 3. Allocation log expander (Task 3)

Sotto le KPI cards, sopra ai grafici, expander `📋 Log dettagliato del
processo di allocazione`. Mostra step-by-step le righe di
`proposal.allocation_log` con le righe `Step N` in grassetto.

Visibile sempre, non solo con maximize ON — anche lo standard pass
produce 4 righe di summary che aiutano a capire cosa è successo.

### 4. Click bond → Borsa Italiana (Task 4)

Sotto il cashflow timeline, tabella compatta con
`st.column_config.LinkColumn` che apre la scheda BI in una nuova tab.

URL pattern (verificato sicuro indipendente da MOT/EuroTLX):

```
https://www.borsaitaliana.it/borsa/cerca-titolo.html?search=<ISIN>
```

Colonne: Gradino · Tipo (emoji) · Nome · ISIN · Capitale · YTM · 🔗 Borsa Italiana.

I tooltip Plotly del ladder chart restano informativi ma il clic-effettivo
sta nella tabella sotto — Plotly non supporta link nei hover su Streamlit.

## Reference A/B test

Stesso input dell'utente originale (budget €50k, 10 gradini, 10y):

| Metric | maximize=False | maximize=True | Δ |
|---|---:|---:|---|
| Allocato | €39,117 | €49,473 | **+€10,356** |
| Coverage | 78.2 % | **98.9 %** | +20.7 pp |
| Bond selezionati | 23 | 21 | -2 |
| Bond scartati | 35 | 61 | +26 (più candidati visti) |
| Wavg YTM | 3.04 % | **3.25 %** | +0.21 pp |
| Wavg duration | 5.39 y | 6.34 y | +0.95 y |
| Composizione gov_ita | 69.3 % | 78.8 % | +9.5 pp |
| Composizione corp | 19.5 % | 19.2 % | -0.3 pp |
| Composizione gov_foreign | 11.2 % | 2.0 % | -9.2 pp |
| `allocation_log` entries | 4 | 25 | +21 |
| `yield_without_maximization` | None | 0.0304 | — |

L'output del run "maximize=True" trade-off è in realtà **positivo sul
yield** in questa specifica configurazione (3.25 % vs 3.04 %): la
tolerance expansion ha trovato bond a yield più alto fuori dalla finestra
originale ±6m. Il dataset corrente premia la flessibilità. In altre
configurazioni il segno può invertirsi — la UI mostra in entrambi i casi
"impatto Δ pp" così l'utente vede subito il trade-off reale.

## Backward compatibility

- **API LadderBuilder invariata**: il default `maximize_allocation=False`
  preserva il comportamento v3.1.0 byte-per-byte (tutti i 10 test esistenti
  continuano a passare).
- **Schema `LadderProposal` esteso** con due campi opzionali con default
  → costruttori positional/keyword esistenti continuano a funzionare.
- **3 test nuovi** in `tests/test_ladder_builder.py` lockano il
  comportamento nuovo:
  - `test_allocation_log_always_populated_even_without_maximize`
  - `test_maximize_allocation_runs_extra_steps`
  - `test_maximize_allocation_off_does_not_lose_existing_behaviour`

## File toccati

| File | Tipo |
|---|---|
| `strategies/bonds_income/ladder_builder.py` | esteso (config + proposal + 4 nuovi helper) |
| `ui/pages/13_Ladder_Builder.py` | esteso (toggle, warning, log expander, link table) |
| `tests/test_ladder_builder.py` | +3 test |
| `CHANGELOG.md`, README, `_migration_log/V3_1_1_*.md` | docs |
