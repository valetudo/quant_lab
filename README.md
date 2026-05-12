# Quant Lab

A personal multi-strategy quantitative trading framework with a static strategic allocation,
walk-forward validated strategies, a bond-ladder tracker, and a Streamlit dashboard.

Single-user, manual rebalancing: the system signals drift and suggests actions; the
user executes trades at the broker.

## What it does

- **Static strategic allocation** across three sleeves — bonds 50% / passive equity 30% / opportunistic 20%.
- **Plug-and-play strategies** auto-discovered from `strategies/<id>/`. Drop a folder, restart Streamlit, it shows up.
- **Walk-forward backtests** with survivorship-bias correction and a hard SPY benchmark gate. A strategy that beats overfit metrics but loses to buy-and-hold gets archived (see `_migration_log/V5_VS_SPY_DECISION.md`).
- **Bond ladder tracker** for Italian government + corporate bonds with target buckets, drift alerts, and gap-fill suggestions.
- **Streamlit dashboard** for portfolio overview, strategy listing, backtest runner, data status, bond screener, debug logs, and ladder management.

## Architecture

```
            ┌──────────────────────────────────┐
            │   Static Strategic Allocation    │   50/30/20  bonds/equity/opportunistic
            │   (configs/portfolio.yaml)       │   drift > 5pp ⇒ UI alert
            └────────────┬─────────────────────┘
                         │
       ┌─────────────────┼─────────────────────────────┐
       ▼                 ▼                             ▼
  ┌─────────┐     ┌────────────┐                ┌─────────────┐
  │  Bonds  │     │   Equity   │                │ Opportunist.│
  │  50%    │     │    30%     │                │     20%     │
  │ ladder  │     │  passive   │                │  (cash)     │
  │ (manual)│     │  VWCE UCITS│                │   reserved  │
  └─────────┘     └────────────┘                └─────────────┘
```

See `docs/architecture.md` for the full picture.

## Layout

```
core/                  Framework — data, strategy ABC, backtest engine, analytics, IO, streaming
strategies/            Concrete strategies — bonds_income, passive_equity, pattern_finder (scaffold), _archived/
portfolio/             Sleeve model — static_allocator, state
ui/                    Streamlit multi-page app + shared helpers
scripts/               CLI — backtests, walk-forward, data refresh, FMP verification
configs/               YAML — global, portfolio, per-strategy
tests/                 Cross-cutting test suite (78 tests)
data_storage/          Local cache root — DuckDB cache, bonds.db, positions.parquet (gitignored)
outputs/               Backtest outputs (gitignored)
docs/                  Architecture, per-strategy docs, archived strategies
_migration_log/        Phase reports, decision records, audit logs (kept for traceability)
```

## Quick start

```bash
# from quant_lab/
python -m venv .venv
.venv\Scripts\activate           # Windows (or source .venv/bin/activate on POSIX)
pip install -r requirements.txt

# Configure secrets
cp .env.example .env             # then edit and set FMP_API_KEY

# One-time data setup (if you also run the sister bonds/ repo)
python scripts/migrate_bonds_db.py
python scripts/migrate_prices_to_fmp.py --start 2016-01-01 --end 2025-12-31

# Run the dashboard
streamlit run ui/main.py
```

Windows shortcut: double-click `start.bat` (or `start.ps1` from PowerShell). The dashboard opens at <http://localhost:8501> and lands on the **🏠 Home** page.

## Typical workflow

### First time — build the portfolio from scratch

1. **🏠 Home** → "Costruisci portfolio da zero"
2. **🏗️ Costruisci Portfolio** → pick your own asset allocation (e.g. 50/30/20)
3. Build each section:
   - **💰 Bonds** — Ladder Builder generates a concrete purchase proposal
   - **🌍 Equity** — guided ETF selection (VWCE recommended)
   - **🎯 Alternative** — explore active strategies (Pattern Finder + future)

### Existing investor — track what you already own

1. **🏠 Home** → "Aggiorna posizioni esistenti"
2. **📥 Aggiorna Posizioni** → enter bond + ETF holdings manually
3. **📊 Portfolio Overview** → real-time P&L, allocation drift, per-asset detail

The **Backtest Lab** (was Backtest Runner) is in **🛠️ Strumenti** — only needed when validating an active alternative strategy.

### Import from broker (Directa)

Quant Lab supports drag-and-drop import of the standard Directa XLSX portfolio export:

1. From the Directa portal: **Portafoglio → Esporta XLSX**.
2. In Quant Lab: **📥 Aggiorna Posizioni** → tab **📤 Import da Broker (XLSX)** → drop the file.
3. Type the cash balance (not included in the XLSX).
4. Review the diff (new / updated / closed positions) and confirm which to sync.
5. The page then shows a gap-analysis (current vs target allocation) with actionable suggestions.

The pattern extends to any other broker that exports a structured file (Fineco CSV, IBKR XML, etc.) — the reconciliation engine is broker-agnostic.

## Configuration

`configs/global.yaml` holds path defaults for the DuckDB cache and the bonds SQLite DB.
Env vars override (see `.env.example`):

| Env var | Purpose |
|---|---|
| `FMP_API_KEY` | **Required.** Financial Modeling Prep Premium API key. |
| `QUANT_LAB_DATA_PATH` | Optional. Override data_storage root. |
| `QUANT_LAB_BONDS_DB_PATH` | Optional. Override path to `bonds.db`. |
| `GDS_DB_PATH` | Optional. Override path to the global DuckDB. |

`configs/portfolio.yaml` declares the sleeve model — edit `total_capital_eur` and
`strategic_allocation` to match your situation. Drift alert threshold is
`drift_threshold_pp` (default 5.0).

## Strategies

| Strategy | Sleeve | Status | Notes |
|---|---|---|---|
| `bonds_income` | bonds 50% | active | Manual ladder tracker, target buckets, drift alerts. |
| `passive_equity` | equity 30% | active | Buy-once-hold-forever VWCE.MI UCITS ETF — Vanguard FTSE All-World, ~3700 holdings, developed + emerging, TER 0.19% (VT proxy fallback for backtests). |
| `pattern_finder` | opportunistic 20% | scaffold | Adapter for an external pattern-mining repo. Not yet wired. |
| `quality_stocks` V5 | (archived) | archived | Reached STRONGLY ROBUST 8/8 in WF but lost -4.6 pp/yr to SPY → archived. See `_migration_log/V5_VS_SPY_DECISION.md`. |

## Adding a strategy

1. Create `strategies/<id>/` containing `strategy.py` (subclass `core.strategy.base.Strategy`) and `config.yaml`.
2. Restart Streamlit. The registry auto-discovers it; the Strategies page lists it under its sleeve.

The reference implementation lives in `strategies/_examples/dummy_buy_and_hold.py`.
Full walkthrough in `docs/adding_a_strategy.md`.

## Phase history

| Phase | Focus | Report |
|---|---|---|
| Phase 1 | Monorepo scaffolding from pair_trading_ITA + bonds | `_migration_log/PHASE1_REPORT.md` |
| Phase 2 | FMP provider, Quality Stocks baseline, Master Allocator | `_migration_log/PHASE2_REPORT.md` |
| Phase 2.5 | Bonds Screener filters, Live equity streaming | `_migration_log/PHASE2_5_REPORT.md` |
| Phase 3 | Static allocation, Portfolio Overview, Quality Stocks V5 | `_migration_log/PHASE3_REPORT.md` |
| Quality Stocks V5 | Full-history walk-forward + survivorship correction | `_migration_log/V5_FULL_VALIDATION_REPORT.md`, `_migration_log/V5_SURVIVORSHIP_VALIDATION_REPORT.md` |
| V5 vs SPY decision | Benchmark gate fail → archive V5, flip equity sleeve to passive CSPX | `_migration_log/V5_VS_SPY_DECISION.md` |
| v1.1.0 equity switch | CSPX (S&P 500) → VWCE (FTSE All-World global), addresses US-only bias | `_migration_log/EQUITY_SLEEVE_GLOBAL_DECISION.md` |
| Phase 4 | Restructure to 50/30/20, modular strategy registry, passive equity sleeve | (see `CHANGELOG.md`) |
| Pre-v1.0.0 | Code cleanup, security audit, git init | `_migration_log/cleanup_inventory.md`, `_migration_log/SECURITY_AUDIT.md` |

## License

MIT — see `LICENSE`.
