# Changelog

All notable changes to **Quant Lab**. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
