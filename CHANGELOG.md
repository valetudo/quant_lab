# Changelog

All notable changes to **Quant Lab**. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.0] — 2026-05-12

### Added

- **Directa XLSX importer** — drag-and-drop import of the standard Directa
  portfolio export (`P_TOTALE_<account>_<YYYYMMDD>.xlsx`). New tab
  **📤 Import da Broker (XLSX)** as the first tab inside
  `3_Aggiorna_Posizioni.py`.
  - `core/data/importers/directa_xlsx.py` — `DirectaXLSXImporter` parser,
    `DirectaPosition` + `DirectaPortfolioSnapshot` dataclasses, heuristic
    bond/equity classifier (pattern match on instrument name + ISIN
    prefix + Directa ticker shape).
- **Reconciliation engine** — `portfolio/reconciliation.py` diffs the
  broker snapshot against the active rows of the unified
  `PositionTracker` and yields a `ReconciliationReport` with
  `new` / `updated` / `closed` / `unchanged` deltas. `apply_deltas()`
  materialises only the deltas the user checked in the data-editor.
- **Gap analysis** — `ui/utils/gap_analysis.py` (`show_gap_analysis`,
  `show_snapshot_summary`). Two side-by-side donut charts (current vs
  target), a per-sleeve gap table, and actionable suggestions in plain
  Italian ("Apri il Ladder Builder per generare proposta", "Apri Equity
  — World ETF per acquistare VWCE", …).
- **Manual cash-balance input** — Directa's XLSX excludes cash, so the
  Import tab asks the user to type it after upload.
- 9 new tests in `tests/test_directa_importer.py` (parser + reconciliation
  edge cases, fixture-gated when the user's real export is present).

### Architecture

- **Broker-agnostic by design**: reconciliation diffs by ISIN; any future
  importer (Fineco CSV, IBKR XML, …) that yields a snapshot of the same
  shape plugs in without UI changes.
- **`Position` quantity convention preserved**: Directa exports bond
  `Quantita` as nominal EUR (matches v2.0.x convention), so the bond
  value math `quantity × price / 100` keeps working unchanged.

### Limitations

- Purchase date is not in the Directa export → newly imported rows use
  today's date.
- Asset classification is heuristic; the reference fixture classifies
  12/12 correctly, but edge-case instruments may fall through to
  `"unknown"`. The UI flags any "unknown" in an expander and skips
  them from the apply step.
- `data_storage/imports/` is gitignored — uploaded broker files stay
  local-only.

### Reference

- See `_migration_log/V2_1_0_DIRECTA_IMPORT.md` for the design rationale,
  alternatives considered, and reference-run numbers.

## [2.0.1] — 2026-05-12

Hotfix: three issues identified during v2.0.0 production use.

### Fixed

- **Inflated bond sleeve totals were caused by duplicate-ISIN inserts**, not by a math error.
  Diagnosis on the user's parquet showed one ISIN with 12 active rows and several with 4 — the
  `quantity × price / 100` formula is correct under the documented "nominal EUR" convention
  used uniformly across all write paths (Aggiorna Posizioni form, Ladder Builder confirmation,
  legacy `LadderTracker` dual-write). Root cause: `PositionTracker.add_position` had no
  duplicate guard, so repeated form submissions or re-runs of the Ladder Builder confirmation
  silently appended copies.
- `PositionTracker.add_position` now raises `ValueError` when an active row with the same
  ISIN already exists. Pass `allow_duplicate=True` to bypass (test fixtures only).
- **Ladder chart legibility in dark mode**: every annotation, axis title, tick label, legend
  and title now uses a theme-neutral mid-grey (`#888888`) with transparent paper + plot
  backgrounds. Labels read cleanly under both the light and dark Streamlit themes. Same
  treatment applied to the cash-flow timeline.

### Added

- **Per-row removal UI** in `3_Aggiorna_Posizioni.py` for the Bonds, Equity and Alternative
  tabs. Two-step confirmation, reason selectable (`sold` / `matured` / `error_correction`).
  Goes through the existing `PositionTracker.remove_position()` (soft-delete, position
  remains in the parquet with `status` flipped).
- **Full reset workflow** (also in Aggiorna Posizioni) — text-confirmation guard (`RESET`),
  backs up the parquet to `positions_reset_backup_<ts>.parquet` before flipping every active
  row to `status: reset`.
- **Aggiorna Posizioni link** in `1_Portfolio_Overview.py` so management is a single click
  away. The Overview keeps the read-only role; all mutations go through Aggiorna Posizioni.
- **Duplicate-ISIN error toast**: the Aggiorna Posizioni bond + ETF add forms now catch
  the new `ValueError` and surface it as a red banner with the Italian explanation message,
  instead of bubbling up as an uncaught exception.

### Migration

- Pre-v2.0.1 parquet backed up to
  `data_storage/positions/portfolio_positions_pre_v201_backup.parquet` (gitignored).
- **No schema migration needed** — the math was correct. Users can either remove duplicate
  rows manually via the new UI or click the Reset Portfolio button and re-enter cleanly.

## [2.0.0] — 2026-05-12

### MAJOR — UX refactor: from development framework to operational tool

The codebase below the UI is largely unchanged; the navigation, the
landing experience, and the position-tracking layer were rewritten to
treat Quant Lab as a daily operational tool rather than a research
notebook.

### Added

- **`portfolio/position_tracker.py`** — unified `PositionTracker` for all
  asset classes (bond / equity / alternative / cash), backed by
  `data_storage/positions/portfolio_positions.parquet`. Provides
  `add_bond` / `add_equity` / `add_alternative` helpers, status
  tracking, and `unrealized_pnl()` / `current_value_eur()` aggregates.
- **`portfolio/price_provider.py`** — `PriceProvider` looks up current
  prices across asset classes (bonds.db for bonds, FMP parquet store
  with VWCE/IWDA/SWDA/CSPX/VUSA/VUAA ISIN→ticker mapping for ETFs,
  cost-basis fallback for alternative).
- **UI page `0_Home.py`** — landing with binary choice (Costruisci da
  zero / Aggiorna posizioni). Shows current sleeve breakdown if
  positions exist.
- **UI page `2_Costruisci_Portfolio.py`** — guided build workflow.
  Step 1: pick free-form bond/equity/alternative percentages.
  Step 2: launch the dedicated section page with the per-sleeve budget.
- **UI page `3_Aggiorna_Posizioni.py`** — manual position entry tabs for
  bonds + ETFs. Writes through `PositionTracker`. Shows live asset
  allocation from the positions entered.
- **UI page `5_Equity_World_ETF.py`** — VWCE-first guidance: hero banner,
  five-reason rationale, ETF comparison table (VWCE / IWDA / SPYY /
  VUSA / CSPX), purchase form, fiscal notes for IT retail.
- **UI page `6_Alternative_Strategies.py`** — registry-driven listing
  of opportunistic strategies with status badges, README expander,
  position registration form, and a button to open the strategy in
  Backtest Lab.
- **UI page `7_Strumenti.py`** — hub for power-user pages (Backtest Lab,
  Bonds Screener, Data Status, Debug Logs, Ladder Builder).
- **Bonds refresh button** in the renamed `4_Bonds_Ladder.py`. Delegates
  to `scripts/refresh_bonds_db.py` which copies the sister `bonds/`
  repo's freshly-scraped DB when available and returns a structured
  status the UI can surface.
- **`scripts/refresh_bonds_db.py`** — scaffold for in-place bonds.db
  refresh (today: copy from sister repo).

### Changed

- **UI page `1_Portfolio_Overview.py`** rewritten as a real-position
  performance tracker (P&L per position and per asset class, pie chart,
  per-asset-class tabs). Decoupled from the static-allocation model.
- **Page renames**: `3_Backtest_Runner.py` → `9_Backtest_Lab.py` with a
  disclaimer banner; `5_Bonds_Screener.py` → `10_Bonds_Screener.py`;
  `4_Data_Status.py` → `11_Data_Status.py`;
  `6_Debug_Logs.py` → `12_Debug_Logs.py`;
  `8_Bond_Ladder.py` → `4_Bonds_Ladder.py`;
  `9_Ladder_Builder.py` → `8_Ladder_Builder.py`. Streamlit sidebar now
  reflects workflow priority (numerals 0–7 = primary, 8–12 = advanced).
- **`ui/main.py`** redirects to `0_Home.py` on entry.
- **`strategies/bonds_income/positions_io.py`** `add_position()` now
  dual-writes to the unified `PositionTracker` so cross-asset pages
  see every bond added via the legacy Ladder forms.

### Removed (from top-level nav)

- **`ui/pages/2_Strategies.py`** archived to
  `ui/_archived/2_Strategies.py.bak` — its function is fully absorbed
  by `6_Alternative_Strategies.py` (registry-driven) and the per-asset
  pages. The file is preserved for history.

### Architectural notes

- **Asset allocation is no longer hard-coded 50/30/20.** The Costruisci
  workflow asks the user every time; `configs/portfolio.yaml` keeps the
  default only as a fallback for the legacy `PortfolioState` /
  `StaticPortfolio` code paths.
- **Single source of truth for positions**: `portfolio_positions.parquet`
  via `PositionTracker`. The bond-specific `data_storage/bonds/positions.parquet`
  stays for `LadderTracker`'s detail-rich view (composition, gaps,
  cash flow) and is kept in sync via dual-write.
- **Backward compatibility absolute**: every v1.x public API still works;
  88 tests still green.

### Documentation

- **`_migration_log/V2_UX_REFACTOR.md`** — full rationale, side-by-side
  navigation diff, lessons learned.

## [1.2.0] — 2026-05-12

### Added

- **Bond Ladder Builder** — given a budget + number of rungs + max duration, generates a concrete bond purchase proposal respecting a per-rung composition target (default 50 % BTP / 25 % corporate-EUR / 25 % gov-foreign-EUR).
  - `strategies/bonds_income/ladder_builder.py`: dataclass schema (`LadderBuilderConfig`, `SelectedBond`, `SkippedBond`, `RungProposal`, `LadderProposal`) + the `LadderBuilder` engine with quality filters (rating, callable, subordinated exclusion), lot-size handling, and per-issuer concentration cap.
  - **Adaptive logic**: when the best foreign sovereign in a rung's tolerance window fails the triple quality filter (yield ≥ best BTP, rating ≥ A-, liquidity ≥ €100k/day where data available), the 25 % foreign weight collapses into the BTP slot and the rung becomes 75/25.
  - `core/data/bonds_universe.py`: `BondsUniverseLoader` wraps `BorsaItalianaProvider` and adds the columns the builder needs but the underlying schema lacks (`category`, `issuer`, `rating_score`, `is_subordinated`, `lot_size_eur`, `coupon_rate`, `coupon_frequency`, `yield_net`, `price_clean`). Includes a hard-coded sovereign-rating fallback table since the DB carries no per-bond ratings.
  - `strategies/bonds_income/ladder_builder.format_broker_list()`: plain-text purchase list ready to copy into a broker order screen.
  - `strategies/bonds_income/ladder_builder.compute_next_12m_cashflow()`: aggregate expected cash (coupons + maturities) over the next 12 months.
- **UI page `9_Ladder_Builder.py`** — storytelling-first design.
  - Header didattico explaining what a bond ladder is in plain Italian.
  - Form for budget / n_rungs / max_duration + advanced settings (composition tilt, rating gates, concentration cap).
  - KPI cards in plain Italian (Capitale impiegato, Rendimento medio annuo, Cash prossimi 12 mesi, Numero di bond).
  - Selected bonds table with Italian column headers + emoji-prefixed category labels.
  - Skipped-bonds expander with reasons translated to plain Italian — full transparency on why a candidate was dropped.
  - Concentration + adaptive-redistribution banners.
  - Textual "Riassunto a parole" summary for non-graphic readers.
  - Actions: CSV export, broker list, confirm acquired positions.
- **Storytelling visualizations** (`ui/utils/ladder_viz.py`):
  - `build_ladder_chart(proposal)`: a literal horizontal ladder — each rung a segmented bar within its tolerance window, colored by category (green = BTP, orange = corporate, blue = foreign).
  - `build_cashflow_timeline(proposal)`: future events on a horizontal spine, small grey coupons + large green maturities with euro labels, floating 12-month aggregate annotation.
- **Confirmation workflow**: from the Builder page, the user enters real broker-executed prices and the system registers each line into the existing `LadderTracker` (`positions.parquet`) via the unchanged `add_position` API.
- **10-test coverage** for the builder (`tests/test_ladder_builder.py`): config validation, happy-path multi-rung, adaptive redistribution when foreign fails rating, lot-size skip recording, weighted-aggregate maths, broker-list format.
- `_migration_log/bonds_db_data_gaps.md`: catalog of columns the spec assumes but bonds.db doesn't carry, plus the conservative defaults the builder applies.

### Changed

- `ui/pages/8_Bond_Ladder.py`: added an info banner linking to the new Ladder Builder for the "build from scratch" workflow.

### Notes

- **No live trading**. The builder produces a proposal a human then executes manually at a retail broker.
- **bonds.db gaps gracefully degraded**: corporate per-bond ratings, daily volumes, first-call dates, and coupon frequencies are absent in the current schema. The builder falls back to: sovereign-rating table for govts (S&P 2026 Q1), name-pattern detection for subordinated/callable, €1000 face / annual coupon defaults, and silently skips the liquidity filter. All documented in `_migration_log/bonds_db_data_gaps.md`.
- **Smoke test on real bonds.db** (`budget=€50k, 10 rungs, 10y`): 23 bonds selected, 32 skipped, allocated €38,306 (23 % unallocated due to lot-size slop), wavg YTM 2.97 % net, duration 5.47 y, composition 68.5/20.0/11.5 vs target 50/25/25, 5 rungs adapted (foreign rating too low — only BBB- Romania/Hungary in window).

## [1.1.0] — 2026-05-11

### Changed

- **Equity sleeve switched from CSPX (S&P 500 USA) to VWCE (FTSE All-World global).**
  - Rationale: address unexamined US-centric bias inherited from the Quantopian era.
  - VWCE.MI = Vanguard FTSE All-World UCITS ETF, ISIN IE00BK5BQT80, ~3700 holdings, developed + emerging markets, TER 0.19 % (reduced from 0.22 % in Oct 2025), accumulating, Borsa Italiana in EUR.
  - Default symbol in `strategies/passive_equity/config.yaml`, `strategies/passive_equity/strategy.py`, `portfolio/state.py`, `ui/pages/1_Portfolio_Overview.py`, `ui/pages/3_Backtest_Runner.py`, `scripts/run_backtests.py` all updated.
  - Backward compatible: CSPX preserved as alternative in config notes; `RETAIL_PROXIES` keeps CSPX→SPY for anyone using v1.0.0 setups.

### Added

- `VWCE.MI/.L/.DE/.AS` and `VWRL.L` → `VT` (Vanguard Total World) proxy mappings in `core.data.storage.DataStorage.RETAIL_PROXIES` for backtests when local FMP cache lacks VWCE (it only listed in 2019).
- `IWDA.AS/SWDA.L/EUNL.DE` → `URTH` (iShares MSCI World, US-listed) proxy mappings for the MSCI World developed-only alternative documented in the strategy README.
- `_migration_log/EQUITY_SLEEVE_GLOBAL_DECISION.md` — full rationale, trade-offs, and reversibility notes for the switch.
- Updated `strategies/passive_equity/README.md`, root `README.md`, `docs/architecture.md`, and `configs/portfolio.yaml` notes.

### Notes

- No code logic changed in `passive_equity/strategy.py` — only the default symbol and the inline proxy table.
- Allocation framework unchanged (still 50 / 30 / 20).
- Tests not re-run (config-only change, no logic touched). The default-config test was updated to assert `VWCE.MI` instead of `CSPX.L`.

## [1.0.0] — 2026-05-11

First public release. Stable framework, documented strategies, full test suite, and a security-audited codebase.

### Added

- **Static strategic allocation** at 50/30/20 (bonds / passive equity / opportunistic), declared in `configs/portfolio.yaml` with a 5 pp drift threshold.
- **Plug-and-play strategy registry** (`core.strategy.registry.StrategyRegistry`): drop a folder under `strategies/<id>/` with `strategy.py` + `config.yaml` and it auto-discovers on Streamlit restart. No UI code change required.
- **Passive equity sleeve** — `strategies/passive_equity/` (buy-once-hold-forever CSPX.L UCITS ETF, with SPY proxy fallback via `DataStorage.get_prices_with_proxy`).
- **Pattern Finder adapter scaffold** — `strategies/pattern_finder/` ready to wire to an external pattern-mining repo. Status: `scaffold`.
- **Bond ladder tracker** — target buckets (1/3/5/7/10y), 70/30 sovereign/corporate split, drift alerts, candidate suggestions filtered by bucket and yield.
- **Streamlit dashboard** with 7 pages: Portfolio Overview, Strategies, Backtest Runner, Data Status, Bonds Screener, Debug Logs, Bond Ladder.
- **Walk-forward backtest harness** with survivorship-bias correction (FMP constituent history) and SPY benchmark gate.
- **DuckDB FMP cache** at `data_storage/cache/fmp_cache.duckdb` for price + fundamentals reuse across backtests.
- **`Strategy` ABC** in `core/strategy/base.py` with `on_init` / `generate_signals` / `manage_positions` hooks.
- **78-test cross-cutting suite** covering portfolio, ladder, registry, FMP provider, backtest engine, streaming runner, and metrics.
- **Env-var path overrides** — `QUANT_LAB_DATA_PATH`, `QUANT_LAB_BONDS_DB_PATH`, `GDS_DB_PATH`, `QUANT_LAB_BONDS_SOURCE` — so the repo is portable across machines without editing YAML.
- **`.env.example`** template with documented variables.

### Changed

- **Allocation**: 60/30/10 → **50/30/20** after the V5 archival, expanding the opportunistic sleeve from 10% to 20%.
- **Equity sleeve**: active Quality Stocks V5 strategy → passive CSPX.L UCITS ETF, after the benchmark gate showed V5 trailed SPY by -4.6 pp/yr despite passing all eight in-sample WF robustness tests.
- **`configs/global.yaml`** sanitized — personal absolute paths replaced with `null` defaults that fall back to repo-relative resolution, env-overridable.
- **`core/data/storage.py`** — `RETAIL_PROXIES` (CSPX.L→SPY, VWCE.DE→IVV, etc.) typed with `ClassVar` to avoid dataclass field collision; `get_prices_with_proxy()` added.
- **`scripts/migrate_bonds_db.py`** — hardcoded `G:/` path replaced with repo-relative default + `QUANT_LAB_BONDS_SOURCE` override.

### Removed

- **Quality Stocks V5** strategy moved to `strategies/_archived/quality_stocks/` with full ARCHIVED.md and final decision report (`_migration_log/V5_VS_SPY_DECISION.md`).
- **`portfolio.aggregator` and `portfolio.master_allocator`** kept only as deprecation shims emitting `DeprecationWarning` — the new sleeve model lives in `portfolio.static_allocator` + `portfolio.state`.

### Security

- Audited all source for credentials and personal paths before the first push. See `_migration_log/SECURITY_AUDIT.md`.
- Sanitized one masked API-key fragment from a migration log.
- Sanitized three hardcoded `G:/` paths to env-overridable repo-relative resolution.
- `.gitignore` covers `.env`, `data_storage/cache/`, `data_storage/prices/`, parquet/duckdb/sqlite files, `outputs/`, and IDE/OS scratch.

## Pre-1.0.0 history

See `_migration_log/INDEX.md` for a chronological index of all phase reports. Highlights:

- **Phase 1** — monorepo scaffolding from `pair_trading_ITA` + `bonds` repos.
- **Phase 2** — FMP provider, Quality Stocks baseline, Master Allocator scaffold.
- **Phase 2.5** — Bonds Screener filters, Live equity streaming with `core.backtest.streaming`.
- **Phase 3** — static allocation, Portfolio Overview page, Quality Stocks V5 walk-forward refinement.
- **Quality Stocks V5 validation** — full-history 17y walk-forward + survivorship-bias correction.
- **Equity sleeve comparison** — 5 passive allocations benchmarked, CSPX UCITS picked.
- **Phase 4** — restructure to 50/30/20, modular strategy registry, passive equity sleeve.
