# v3.0.1 — Bond DB refresh reale con progress UI

## Motivazione

In v3.0.0 il bottone "🔄 Aggiorna prezzi bonds" sulla pagina Bond Ladder
era uno scaffold: chiamava `scripts/refresh_bonds_db.py` che si limitava
a copiare l'eventuale `bonds.db` dal sister repo `bonds/` (se la
scraping era stata eseguita lì a parte).

User feedback:

> *"Vorrei una progressbar dell'update dei prezzi, vedere tempo rimanente
> indicativo e sapere che sta facendo lo scraping da Borsa Italiana, e
> quando ha finito un popup."*

## Soluzione

Integrazione cross-repo con `bonds/`
(<https://github.com/valetudo/bonds>), che già contiene uno scraper
Selenium professional-grade per Borsa Italiana (advanced-search via
XHR pagination, 76 profili per refresh full ≈ 5–10 min).

### Schema compatibility — Scenario A (identici)

I due `bonds.db` (sister repo e Quant Lab) hanno **lo stesso schema**:
`bonds`, `bond_prices`, `scrape_runs`. Nessun adapter necessario. La
classe `Database` del sister repo viene istanziata con
`Database(path=<quant-lab-bonds-db>)` e scrive direttamente sul DB di
Quant Lab. Lo schema viene auto-creato da `_ensure_schema()` se il
file non esiste.

### Architettura

```
core/data/sister_repos.py        — dynamic locator + importer per il bonds/ repo
core/data/refresh_bonds.py       — worker thread + state file JSON
ui/components/bonds_refresh_progress.py — UI panel: idle/running/completed/failed/cancelled
ui/pages/4_Bonds_Ladder.py       — wired al top della pagina, sopra ai 2 tab
```

### Flusso

1. UI: utente clicca **🔄 Aggiorna prezzi bonds**.
2. `start_refresh_async()` lancia un thread daemon che:
   - importa `scraper` + `database` dal sister repo
   - costruisce `Database(path=<quant-lab>)` puntando al DB locale
   - chiama `scraper.run_scrape(db, headless=True, page_callback=..., cancel_flag=...)`
3. Lo scraper fa il giro dei 76 profili, chiamando `page_callback(stats)`
   due volte per profilo (inizio + fine). Il backend aggiorna il JSON
   `data_storage/bonds_refresh_state.json`.
4. La UI rilegge il JSON ad ogni rerun e mostra:
   - progress bar `profiles_completed/profiles_total`
   - profilo corrente in italiano (`label` dal `ScrapeProfile`)
   - ETA dinamica (`elapsed_seconds / profiles_completed × remaining`)
   - bottone **❌ Annulla** che setta un `threading.Event` letto da `cancel_flag`
5. A fine scraping: il thread scrive `status: completed` (o `failed` /
   `cancelled`) e `completed_at`. La UI mostra un summary panel con i
   metrics e un `st.toast` di completamento.

### Double-callback handling

Il sister-repo invoca `page_callback(stats)` **due volte per profilo**:
una volta all'inizio (solo `stats.profile` settato) e una volta alla
fine (con `pages`, `rows`, `saved`, `error`). Il backend tiene una
lista `in_progress_profiles` nello state: la prima callback per un
nome aggiunge alla lista (registra `current_profile_label`); la
seconda rimuove e incrementa `profiles_completed`. Questo è più
robusto del check "saved > 0 or error" della spec originale (un
profilo legittimo con 0 risultati avrebbe falsato il count).

### Resilienza

- **Navigazione UI durante refresh**: il thread continua, il JSON
  cresce, al ritorno l'utente vede progress aggiornato.
- **Chiusura browser tab**: il thread Python continua finché Streamlit
  gira (è `daemon=True` ma vive col processo).
- **Crash Selenium / Chrome**: il worker catch-all wrappa
  `run_scrape()` con `try/except` + `traceback`; lo stato passa a
  `failed` con il traceback completo nel JSON.
- **Restart Streamlit con state "running" orfano**:
  `get_state()` controlla se il `_worker_thread` è vivo; se non lo è
  e `started_at` è più vecchio di 30 minuti, riscrive lo stato a
  `failed` con un messaggio chiaro. Recover automatico al primo
  re-render.
- **Race condition su state file**: scritti via
  `path.with_suffix('.json.tmp')` + `Path.replace()` atomic move →
  letture parziali impossibili.

## Test end-to-end eseguito

Sub-set di 1 profilo (`titoli_di_stato_esteri__fixed__honduras`,
1 bond): ✅ `status=completed`, `bonds_saved=1`, durata 12s, ETA
calcolata correttamente, JSON aggiornato dopo entrambe le callback.

ETA arithmetic test (synthetic state, 60s elapsed / 2 profiles done
su 10): ETA = 240s = 30s/profilo × 8 rimanenti ✅.

Regressione: **97/97 test pytest passano**.

## Limitazioni

- Tempo refresh completo: ~5–10 min per 76 profili sotto carico
  normale BI. Su connessione lenta o BI sotto stress può salire.
- Selenium può fallire se Chrome viene aggiornato e
  webdriver-manager non ha ancora il driver corrispondente
  (auto-update di solito); in quel caso il refresh va a `failed`.
- Lo scraping non ha rate-limiting custom oltre a quello già
  presente in `scraper.py` (delay 0.6–1.5s random tra pagine).

## Backward compatibility

100%: nessuna API Quant Lab modificata. Lo `scripts/refresh_bonds_db.py`
del v2.1.0 resta in piedi (e funzionante) ma la UI ora usa il nuovo
path in-process.
