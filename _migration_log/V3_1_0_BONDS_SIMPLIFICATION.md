# v3.1.0 — Bonds simplification

## User feedback

> *"Per quello che riguarda i bond voglio semplicemente due pagine: in una
> lo screener col grafico e la tabella, in alto la possibilità di aggiornare
> i prezzi che abbiamo già fatto e l'indicazione di quanto i prezzi sono
> aggiornati, e nell'altra il ladder builder così come è adesso. Il tracker
> sparisce, e la pagina strumenti sparisce."*

## Cambiamenti

### Sidebar — 4 voci, ma diverse rispetto a v3.0.x

| v3.0.x | v3.1.0 |
|---|---|
| 💰 Bond Ladder (tab Tracker + tab Builder) | 💰 **Bonds** (Screener + refresh) |
| — | 🏗️ **Ladder Builder** (ex tab 2 della Bond Ladder) |
| 🌍 Equity | 🌍 Equity |
| 🎯 Alternative | 🎯 Alternative |
| 🛠️ Strumenti | — |

Default landing: **Bonds** (era Bond Ladder; concettualmente la stessa
pagina di partenza, riorganizzata).

### Pagina Bonds (nuova `4_Bonds.py`)

Combina due cose:

1. **In cima**: il pannello freshness + refresh (riusato da v3.0.1).
   - Quando idle: banner timestamp ultimo update + bottone "🔄 Aggiorna
     prezzi bonds" nella colonna destra.
   - Quando running: full-width progress bar + ETA + 4 metrics + Annulla.
   - Quando completed/failed/cancelled: banner colorato + summary + dismiss.
2. **Sotto**: il vecchio Bonds Screener (filtri issuer / currency /
   country / duration bucket / yield range / years range / exclude
   callable + inflation-linked) + tabella + yield-curve scatter chart.

Il vecchio bottone "🔄 Refresh scraping" in fondo allo Screener (che
chiamava `provider.refresh()` sincrono) è stato **rimosso** — il
refresh autoritativo è il pannello in cima.

### Pagina Ladder Builder (nuova `13_Ladder_Builder.py`)

Estrazione esatta del **tab Builder** della vecchia
`4_Bonds_Ladder.py`. Contenuto identico:

- Form parametri (budget, n_rungs, max_duration) + impostazioni
  avanzate (tolerance, composition weights, rating, concentration).
- Bottone "Genera proposta" → `LadderBuilder.build()`.
- KPI cards (capitale, rendimento, cash 12m, n° bond).
- Ladder chart (scala letterale) + cash-flow timeline.
- Tabella bond selezionati + skipped expander + riassunto a parole.
- Azioni: CSV export, broker list, conferma posizioni acquisite.
- Workflow conferma → scrive nel `LadderTracker` (parquet locale).

Numero filename `13_` per evitare collisione con `5_Equity_World_ETF.py`
preesistente — l'ordine in sidebar è dichiarato in `st.navigation()` e
non dipende dal prefisso numerico.

### Cosa sparisce

- **Tracker bond** (era tab 1 della vecchia Bond Ladder): contenuto
  cancellato dalla nav. Non riallocato altrove. La pagina nascosta
  `/portfolio-overview` può ancora leggere `data_storage/bonds/positions.parquet`
  se servisse, ma non c'è un'entry-point dedicato.
- **Pagina Strumenti** (`7_Strumenti.py`): hub di link, sostituito
  dalla nav diretta + dalle pagine hidden URL-accessible.
- **Bonds Screener standalone** (`10_Bonds_Screener.py`): contenuto
  migrato in `4_Bonds.py`.

### Pagine archiviate

```
ui/_archived/
├── 4_Bonds_Ladder.py.v310.bak       (era tab Tracker + tab Builder)
├── 7_Strumenti.py.v310.bak           (hub link)
└── 10_Bonds_Screener.py.v310.bak     (Screener standalone)
```

### Pagine hidden invariate (URL-accessible)

`/portfolio-overview`, `/costruisci-portfolio`, `/aggiorna-posizioni`,
`/backtest-lab`, `/data-status`, `/debug-logs`. Sempre raggiungibili,
mai in sidebar. Reattivabili in 5 minuti se servisse.

## Backward compatibility

- Backend invariato: `LadderTracker`, `LadderBuilder`, `BondsUniverseLoader`,
  `PositionTracker`, refresh worker, sister-repo importer — tutti uguali.
- Storage invariato: `bonds.db`, `positions.parquet`,
  `bonds_refresh_state.json`, FMP cache.
- API invariate: nessun import / firma metodo cambiati.
- 97/97 pytest verdi.

## Filosofia

Continuazione del trend v3.0.0: rimuovere quello che non si usa davvero,
lasciare solo gli strumenti operativi essenziali.

Oggi (v3.1.0) il sistema fa quattro cose, tutte indipendenti e tutte
utili: **esplora il catalogo bond, pianifica una nuova ladder, guida la
scelta dell'ETF World, esplora strategie short-term**. Niente portfolio
management quotidiano — quello aspetta l'integrazione API broker.
