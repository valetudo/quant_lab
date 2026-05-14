# v3.0.0 — Strategic Simplification

## Motivazione

User feedback dopo uso reale di v2.2.0:

> *"In base al mio utilizzo, vorrei — senza perdere il codice esistente —
> una versione molto più semplice con solo 4 voci di menu: bond ladder,
> equity, alternative, strumenti. Tutta la parte portfolio management la
> faremo in futuro tramite API broker."*

Il portfolio-management manuale (Aggiorna Posizioni, Costruisci Portfolio,
Import Directa) era un esercizio utile a capire la forma del problema, ma
il workflow operativo quotidiano è troppo macchinoso senza un'integrazione
broker automatica.

## Decisione

Quant Lab passa da "portfolio management complete tool" a
**"research framework + decision tools"**. Costruiamo per quando avremo
le API, non per sostituirle a mano.

## Cosa cambia

### Sidebar

Da 10 voci (v2.2.0) a 4 voci (v3.0.0):

| v2.2.0 | v3.0.0 |
|---|---|
| 🏠 Home | _(rimossa, default landing = Bond Ladder)_ |
| 📊 Portfolio Overview | 🔒 hidden, URL `/portfolio-overview` |
| 📥 Aggiorna Posizioni | 🔒 hidden, URL `/aggiorna-posizioni` |
| 🏗️ Costruisci Portfolio | 🔒 hidden, URL `/costruisci-portfolio` |
| 💰 Bonds — Ladder & Builder | 💰 **Bond Ladder** (invariato) |
| 🌍 Equity — World ETF | 🌍 **Equity** (semplificato, no form) |
| 🎯 Alternative Strategies | 🎯 **Alternative** (hub + Backtest integrato) |
| 🔍 Bonds Screener | 🔒 hidden, accessibile da Strumenti |
| 🔬 Backtest Lab | 🔒 hidden, accessibile da Alternative |
| 📁 Data Status | 🔒 hidden, accessibile da Strumenti |

### Equity page

Rimosso il form "Hai acquistato? Registra la posizione" — la pagina diventa
**pura guida informativa**. Mantenuti banner VWCE, motivazione, comparison
table e note fiscali. Aggiunta sezione "Filosofia" che spiega *perché* la
scelta passiva globale (lezione Quantopian + Quality Stocks V5 vs SPY).

### Alternative page

Rifatta come **hub modulare** keyed off `StrategyRegistry`:

- Raggruppamento per status (`active` / `validated` / `scaffold` / `archived`).
- Per ciascuna strategia: card con id, descrizione, sleeve, bottone "Esplora →".
- Detail view con tre tab: **📖 README** (read da `<strategy>/README.md`),
  **⚙️ Configurazione** (`config.yaml`), **🔬 Backtest Lab** (bottone che
  `st.switch_page` al Lab hidden con `session_state['lab_strategy']` settato).

### Backtest Lab

Hidden dalla nav primaria; codice intatto. Il workflow è:
**🎯 Alternative → strategia → tab Backtest Lab → bottone "Apri Backtest Lab"**.

### Strumenti

Container minimalista con tre bottoni (Bonds Screener / Data Status /
Debug Logs) + un expander "🔒 Pagine portfolio management" che espone le
hidden pages e un secondo expander per il Backtest Lab.

## Implementazione tecnica

### `st.Page(..., visibility="hidden")`

Streamlit 1.36+ supporta `visibility="hidden"` su `st.Page`. La pagina è
ancora dichiarata in `st.navigation([...])` (così `st.switch_page` la
risolve), ma scompare dalla sidebar. Reversibile: rimuovere `visibility="hidden"`
e la pagina torna in nav.

### `default=True`

Sul Bond Ladder, così è il landing implicito (sostituisce la Home).

### `ui/components/mode_badge.py`

Mini helper che renderizza un badge colorato in cima alle pagine:
- `mode_badge("ricerca", ...)` su Equity / Alternative / Strumenti.
- `mode_badge("hidden", ...)` su Portfolio Overview / Costruisci / Aggiorna / Backtest Lab.

Visivamente l'utente capisce subito se è in una pagina "primaria" o "demoted".

## Cosa NON cambia

- Tutti i backend API: `PositionTracker`, `LadderTracker`, `LadderBuilder`,
  `DirectaXLSXImporter`, `StrategyRegistry`, `PriceProvider`.
- Tutti gli storage: `portfolio_positions.parquet`, `positions.parquet`,
  `bonds.db`, cache FMP, `outputs/`.
- 97 test passano identici.
- Tutte le funzionalità delle pagine hidden funzionano completamente.

## Pagine archiviate (`ui/_archived/`)

- `0_Home.py.bak` — landing rimosso, sostituito da Bond Ladder come default.

## Filosofia di base

**Build what you'll actually use.** L'80% degli sviluppatori aggiunge
features. La disciplina è togliere features che non si usano davvero,
lasciandole disponibili per quando serviranno.

Il portfolio-management manuale era un esercizio interessante e ha
chiarito i requisiti per l'integrazione broker futura. Mantenerlo in
nav primaria sarebbe un costo cognitivo costante senza beneficio
proporzionale.

## Reattivare il portfolio management

Quando arriverà l'integrazione API broker (Directa / IBKR), basta:

1. Rimuovere `visibility="hidden"` dalle 3 `st.Page` rilevanti in `ui/main.py`.
2. Riarchiviare `0_Home.py` se serve un dispatcher.
3. (Eventualmente) sostituire il form manuale con un sync automatico via API.

L'operazione richiede ~5 minuti. Niente codice da riscrivere.
