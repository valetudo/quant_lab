# v2.0.0 — UX Refactor (from dev framework to operational tool)

## Why

v1.x was a strong development framework (walk-forward, benchmark gates,
plug-and-play strategy registry) but a mediocre operational tool. Opening
the UI dropped the user into a flat list of pages with no decision flow.

User-stated goal: *"Vorrei aprire la UI e trovarmi una prima pagina dove
decidere se aggiornare le posizioni o costruire da zero, con tre sezioni
chiare (bond/equity/alternative) capibili anche da non addetti ai lavori."*

## What changed

### Navigation

| Before (v1.x) | After (v2.0.0) |
|---|---|
| Pages 1..9, flat list, dev-framework framing | 0–7 workflow-first, 8–12 advanced/diagnostic |
| Portfolio Overview = mix of allocation and backtest stubs | Portfolio Overview = real-position P&L tracker |
| Backtest Runner top-level (always visible) | Backtest Lab inside Strumenti (with disclaimer) |
| Strategies listing page | Absorbed by Alternative Strategies + registry auto-discovery |

Sidebar after the refactor:

```
0_Home.py                  ← landing, binary choice (build vs update)
1_Portfolio_Overview.py    ← real-position tracker, P&L per asset class
2_Costruisci_Portfolio.py  ← guided build workflow with free allocation
3_Aggiorna_Posizioni.py    ← manual position entry for existing investors
4_Bonds_Ladder.py          ← unchanged tracker + refresh button + link to Builder
5_Equity_World_ETF.py      ← VWCE banner + ETF comparison + purchase form
6_Alternative_Strategies.py← opportunistic strategies, registry-driven
7_Strumenti.py             ← hub for power-user pages
8_Ladder_Builder.py        ← unchanged (was 9)
9_Backtest_Lab.py          ← was 3, renamed + disclaimer
10_Bonds_Screener.py       ← was 5
11_Data_Status.py          ← was 4
12_Debug_Logs.py           ← was 6
```

### Backend

- **`portfolio/position_tracker.py`** — single source of truth for all
  asset classes (bond / equity / alternative). One parquet at
  `data_storage/positions/portfolio_positions.parquet` with a flexible
  schema discriminated by `asset_class`. Adds `add_bond` / `add_equity` /
  `add_alternative` convenience methods plus generic CRUD.
- **`portfolio/price_provider.py`** — current-price lookups across asset
  classes. Bond prices from `bonds.db` (`bond_prices` table); ETF
  prices from FMP parquet store via `DataStorage.get_prices_with_proxy`;
  ISIN-to-ticker mapping for the common UCITS ETFs (VWCE, IWDA/SWDA,
  CSPX, SPYY, VUSA, VUAA).
- **Backward compat dual-write**: `strategies/bonds_income/positions_io.py`
  `add_position()` mirrors every bond insert into the unified
  `PositionTracker`. The existing `LadderTracker` API is untouched —
  Bond Ladder and Ladder Builder pages continue to work identically.

### Asset allocation

Hard-coded 50/30/20 is gone. The Costruisci workflow asks the user to
set %, and `configs/portfolio.yaml` keeps the 50/30/20 only as a
fallback default for the legacy `PortfolioState` / `StaticPortfolio`
code paths (Portfolio Overview no longer reads them in the new view).

### Refresh button

The Bonds — Ladder page has a *Aggiorna prezzi bonds* button that
delegates to `scripts/refresh_bonds_db.py`. Implementation is a thin
scaffold: it copies the sister `bonds/` repo's freshly-scraped DB if
present, otherwise returns a structured "scaffold" status the UI can
report to the user ("run `bonds/start.bat` separately, then re-click").
Inline scraping is intentionally deferred — the existing scraper in
the sister repo is ~40 KB and fragile to Borsa Italiana HTML changes;
duplicating it without a migration plan would be a regression risk.

## What didn't change

- Strategy registry + auto-discovery.
- Walk-forward + benchmark gate infrastructure.
- LadderBuilder (v1.2.0) — still the source of truth for bond proposals.
- LadderTracker (Phase 3) — public API preserved, dual-write added.
- FMP integration + DataStorage + retail-proxy mappings.
- 88-test cross-cutting suite — all green.

## Breaking changes

**None at the code/API level.** Anyone importing `portfolio.state`,
`portfolio.static_allocator`, `strategies.bonds_income.ladder.LadderTracker`,
or any of the registry classes sees identical behaviour. The only
behavioural change is that confirming a ladder purchase now also
writes to `data_storage/positions/portfolio_positions.parquet` (in
addition to `data_storage/bonds/positions.parquet`).

## Lessons learned

1. A good UI starts with "what does the user want to do when they open
   the app?", not "what subsystems do we have?"
2. Backtest tooling should be visible but not in the primary flow for
   passive assets — the choice of ETF or ladder is structural, not statistical.
3. Tracking real-position P&L and running backtests are different concerns;
   conflating them on one page (the old Portfolio Overview) made both
   weaker.
4. A unified `PositionTracker` lets the workflow pages stay simple
   (single concept: "the portfolio") while the bond-specific subsystems
   keep their detail-rich schema underneath.
