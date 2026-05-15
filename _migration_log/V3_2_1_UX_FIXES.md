# v3.2.1 — UX fixes minori

## Feedback utente

> *"1) Sezione Azioni nel Ladder Builder, toglila, non fa nulla che mi
> serve. 2) Nella metrica Bond filtrati, dimmi i filtrati sul totale,
> non solo i filtrati."*

## Fix

### 1. Rimozione sezione "🎯 Azioni" dal Ladder Builder

La sezione conteneva due pulsanti residui dell'era v2.x:

- **📋 Lista per broker** — generava un dump testuale dei bond, ormai
  ridondante con l'export CSV/PDF di v3.2.0.
- **✅ Conferma posizioni acquisite** — apriva un form che registrava le
  posizioni nel `LadderTracker` (parquet). Codice morto in v3.x: il
  portfolio management è hidden in attesa dell'integrazione API broker.

Rimossa l'intera coda della pagina (sezione Azioni + display broker-list
+ l'intero confirmation workflow, che senza i pulsanti era irraggiungibile).
La pagina Ladder Builder ora termina con la sezione **📤 Esporta proposta**
(CSV + PDF).

Puliti anche due import diventati inutilizzati: `LadderTracker` e
`format_broker_list`.

### 2. Metrica "Bond filtrati" con totale

Prima: `Bond filtrati: 494` — nessun contesto su quanti bond ci sono
in totale, quindi impossibile capire a colpo d'occhio se i filtri sono
stretti o larghi.

Dopo: valore `494 / 1.847` + sotto-etichetta `26.7% del totale`.

Il denominatore è `len(df)` — il DataFrame del catalogo bond caricato
dal `BorsaItalianaProvider`, cioè **esattamente il set su cui i filtri
operano**. Niente query SQLite separata: usare `len(df)` garantisce
coerenza (una COUNT diretta sul DB potrebbe divergere dall'enrichment
applicato dal provider in fase di load).

## Backward compatibility

100%: nessuna API modificata, solo UI/UX. Test suite invariata
(106/106 verdi). Il `LadderTracker` e `format_broker_list` restano
disponibili come API — è solo la pagina Ladder Builder a non chiamarli
più.
