# v3.1.2 — Optimal-params suggestion for Ladder Builder

## Feedback utente

Screenshot allegato dall'utente:
- **Run 1**: €20k / 5 gradini / 30y → €14,161 allocato (70.8 %, 3.47 % YTM, 12 bond).
- **Run 2**: €20k / **3** gradini / 30y → €10,958 allocato (54.8 %, 3.66 % YTM, 5 bond).

> *"Riducendo il numero di gradini la situazione peggiora. In questo caso
> vorrei che fosse consigliata dal programma all'utente una ottima scelta
> di duration massima e numero gradini in base al budget per avere una
> quasi totale allocazione delle risorse."*

L'intuizione "meno gradini = più budget per gradino = più facile riempire
i lotti" si scontra con un'altra realtà: meno gradini coprono meno
maturity buckets, e a `max_duration=30y` spread su 3 gradini significa
target a 10y / 20y / 30y, dove la bonds.db è sparsa.

Il problema è bivariato (numero gradini × duration). L'utente vuole un
suggerimento esplicito del **sweet spot** per il proprio budget.

## Soluzione

Grid search rapida `(n_rungs, max_duration)` → ranking per coverage.

### Backend — `find_optimal_params()` in `ladder_builder.py`

Nuova funzione che scansiona una griglia di combinazioni
`n_rungs ∈ {3, 5, 7, 10, 12, 15}` × `duration ∈ {5, 8, 10, 15, 20, 30}` (36
combinazioni dopo skip dei pattern non sensati come `n_rungs > duration * 4`)
e ritorna i top N candidati ordinati per:

1. coverage % (primary)
2. weighted_avg_ytm % (tiebreaker)

Con un universo pre-caricato il loop completo gira in **~1 s** (26 ms/build).

```python
@dataclass
class ParamCandidate:
    n_rungs: int
    max_duration_years: int
    coverage_pct: float       # 0..100
    weighted_avg_ytm: float   # decimal
    allocated_eur: float
    n_bonds_selected: int
```

Caratteristiche chiave:

- **Inherits `base_config`**: l'eventuale tweak utente delle impostazioni
  avanzate (composition weights, rating gates, concentration cap) viene
  rispettato. Solo `budget_eur`, `n_rungs` e `max_duration_years` cambiano
  nel grid search.
- **Standard pass only**: usa `_build_standard()` (no maximize fallbacks).
  Il finder confronta le baseline, non i risultati con maximize ON.
- **Fallback < 80 %**: se nessuna combo raggiunge la soglia min_coverage
  (default 80 %), ritorna comunque le top N — la UI mostra un warning
  esplicito così l'utente sa che il budget è il vincolo.

### UI — pannello "🔍 Trova parametri ottimali"

Sopra il bottone "Genera proposta", un nuovo bottone laterale che:

1. Esegue `find_optimal_params` con il budget corrente e i parametri
   avanzati attuali.
2. Mostra un container con le top 5 combinazioni, ciascuna con:
   - Badge `🏆` / `#2` / `#3` / …
   - 4 metric cards: n_rungs · duration · coverage % · YTM % · allocato €
   - Bottone "Usa questi" che setta `st.session_state["lb_n_rungs"]`
     + `st.session_state["lb_max_dur"]` e fa rerun → la form si
     ricarica con i parametri suggeriti.
3. Banner top warning se la migliore opzione è < 80 % (suggerisce di
   alzare il budget o attivare `maximize_allocation`).

Il pannello "stale" sopravvive alle rerun finché l'utente non clicca
"Usa questi" o cambia budget (e ri-clicca "Trova").

## Reference run

A/B sullo scenario dell'utente:

| Setup | Coverage | YTM | Allocato |
|---|---:|---:|---:|
| Default form (5 / 30y) | 70.8 % | 3.47 % | €14,161 |
| Default form (3 / 30y) | 54.8 % | 3.66 % | €10,958 |
| **Top suggerimento (5 / 15y)** | **93.0 %** | **3.21 %** | **€18,605** |
| #2 (5 / 5y) | 84.0 % | 2.83 % | €16,795 |
| #3 (3 / 15y) | 82.5 % | 3.41 % | €16,504 |

L'opzione raccomandata porta da 70.8 % a 93.0 % di allocazione
(+€4,444 messi al lavoro) sacrificando 0.26 pp di yield medio.

## Edge cases gestiti

- **Budget piccolo (€10k)**: nessuna combo supera l'80 % di coverage; il
  fallback ritorna top N comunque, banner avvisa che il budget è il
  vincolo.
- **Budget grande (€100k+)**: tipicamente 5 rungs × 15y produce 97 % di
  coverage. Niente di speciale.
- **Universo vuoto / mancante**: la funzione catch-all skippa le combo
  che lanciano eccezioni; se nessuna riesce ritorna lista vuota.

## Test

Nuovi: `tests/test_ladder_builder.py`:
- `test_find_optimal_params_returns_sorted_candidates`: ordinamento
  coverage desc, ytm tiebreaker.
- `test_find_optimal_params_inherits_base_config_advanced_settings`:
  l'inheritance del base_config rispetta foreign_min_rating &c.

Totale: 100 → **102** test passanti, 0 broken.

## Backward compatibility

- Nessuna firma di `LadderBuilder.build()` o `LadderProposal` modificata.
- `_build_standard()` esisteva già (estratto in v3.1.1).
- Default behaviour: il bottone "Trova parametri ottimali" è opzionale,
  niente cambia se l'utente non lo clicca.
