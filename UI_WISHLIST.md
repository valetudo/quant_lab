# UI Wishlist + Architectural Decisions

Documento vivente che raccoglie issue UI, feature da aggiungere, e decisioni architetturali emerse durante l'uso del sistema. Diventa il payload del prossimo prompt di refinement.

---

## ✅ Completed in Phase 2.5 (2026-05-11)

- **Bonds Screener (page 5)**: filtri `Sovereign nation` + `Duration bucket` (0-2y / 2-5y / 5-10y / 10y+); layout riorganizzato 4×2 colonne.
- **Backtest Runner (page 3)**: live equity curve streaming + bottone Stop (con disclaimer di selection bias). Modalità "Live (interactive)" vs "Batch (no interruption)". Output `metrics_std.json` ora include `early_stopped`, `stop_reason`, `completion_pct`.
- **Quality Stocks (page 7)**: banner rosso OVERFIT in cima alla pagina (sempre visibile), badge verdict in evidenza, tabella per-fold del walk-forward, live mode opzionale.
- **Engine infra**: `core/backtest/streaming.py` (file-based pub/sub via JSONL) + hook opzionale in `PortfolioBacktester`. Backwards-compatible — CLI/walk-forward/pytest non cambiano.

## 🟡 Pending for Phase 3

- **Asset Allocation strategica — 60/30/10 fisso, NO dynamic master allocator tra sleeve.**
  - Bonds sleeve 60% gestito come ladder; no sell per rebalance, scadenza naturale.
  - Equity sleeve 30% Quality Stocks; regime filter (SPY 50/200) opera solo dentro lo sleeve; cash temporaneo resta in EUR sul broker, NON migra a bond.
  - Opportunistic sleeve 10% per Pattern Finder + strategie ad hoc.
- **Portfolio Overview (page 1) popolata**:
  - Allocation pie chart (current vs target)
  - Drift table per sleeve + alert visivo se drift > 5pp
  - Suggerimento ribilanciamento (capitale da aggiungere/togliere) — NON eseguire automaticamente
  - Cash flow projection bond ladder (calendario scadenze + cedole attese)
  - Equity sleeve dashboard (Quality Stocks + eventuali altre strategie equity future)
  - Total P&L scomposto per sleeve
  - Mini chart equity curve totale ultimi 12 mesi
- **Bond ladder design + alerts visivi** su drift > 5pp.
- **BTP/OAT historical price panel** (al momento `bonds_income` gira su panel sintetico flat).
- **Quality Stocks regime fix** — il bond fallback IEF non funziona in regimi di rate-rising (vedi PHASE2_REPORT §11).

## 🔵 Future

- Pattern Finder integration come opportunistic sleeve
- Paper trading connector (live FMP poll + execution simulation)
- Live monitoring dashboard
- Regime-aware allocator (`RegimeAwareAllocator` — placeholder Phase 3)

---

## Decisioni architetturali registrate

### Live backtest streaming — file-based pub/sub
Scelta: JSONL append-only + control file in `outputs/_streams/`. Alternative scartate:
- WebSocket / SSE: overkill, richiede gestione connessione e non sopravvive a hot reload streamlit.
- In-memory `queue.Queue`: non sopravvive a session reset; non condivisibile tra worker e UI process se streamlit forka.
- Multiprocessing: introduce overhead + pickling dei pandas DataFrame del panel.

Trade-off: due piccole letture al secondo del file di controllo. Affidabile, debuggabile (puoi `cat` il JSONL per vedere lo stream), portabile.

### Stop button + selection bias
Lo Stop è un bottone two-step: il primo click mostra un warning dettagliato sul rischio statistico, il secondo conferma. L'output finale è marcato `early_stopped=true` nel `metrics_std.json` così che chiunque riguardi i risultati lo veda.

### Equity sleeve — comportamento in regime bear (carry-over da pre-2.5)
Quando Quality Stocks vede SPY in downtrend (50 MA < 200 MA), la strategia smette di aprire nuove posizioni equity. Il cash che resta dentro lo sleeve equity:
- Resta in **EUR cash** sul conto trading
- NON viene riallocato al bond sleeve
- NON viene parcheggiato in bond ETF (es. IEI/SHV)
- Attende il prossimo rebalance mensile per essere riassegnato a equity se il regime cambia

Nota: in regimi di tassi alti, il cash sul broker può rendere qualcosa (~2% lordo a oggi). Da tracciare nel P&L attribution.

---

## General / Cross-page

- Prima pagina all'apertura: TBD (probabilmente Portfolio Overview quando popolata)
- Tema dark è ok? Light alternativa?
