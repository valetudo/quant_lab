# Cleanup Inventory — Pre-v1.0.0

**Date**: 2026-05-11

## Files removed by category

| Category | Count | Notes |
|---|---:|---|
| `__pycache__/` directories | 206 | All non-`.venv/` pycache dirs |
| `*.pyc` files | 1,684 | Compiled artifacts |
| `.pytest_cache/` | 1 | repo root |
| `.coverage` | 1 | repo root |
| `.ruff_cache/` | 0 | none present |
| `.mypy_cache/` | 0 | none present |
| `.DS_Store` / `Thumbs.db` | 0 | none present |
| `_migration_log/quant_lab_import_issues.txt` | 1 (12 MB) | Phase 2 fix debug dump — historical artefact, no longer informative |
| `outputs/_streams/*` | 4 | live-run streaming debris (JSONL + control JSON) |

## Space freed

- **Before cleanup**: 287 MB
- **After cleanup**: 247 MB
- **Freed**: ~40 MB (mostly the import-issues dump + pyc files)

## NOT touched (kept by design)

- `_backups/` (135 MB) — pre-monorepo snapshots, local-only
- `_migration_log/*` except the import-issues dump — historical reports + decision documents
- `strategies/_archived/quality_stocks/` — archived code with `ARCHIVED.md`
- `scripts/_archived/*` — Phase V/S scripts kept for reproducibility
- `ui/_archived/7_Quality_Stocks.py.bak` — UI page backup
- `data_storage/` (131 MB) — local price cache, git-ignored
- `outputs/` (~7 MB, definitive backtest reports) — derived data, git-ignored

## Final root inventory

```
quant_lab/
├── .env                    # local secrets, gitignored
├── .gitignore
├── LICENSE
├── README.md
├── UI_WISHLIST.md          # design notes (kept as project history)
├── __init__.py             # repo-level __init__
├── _backups/               # pre-monorepo snapshots (local-only, gitignored)
├── _migration_log/         # phase reports + INDEX.md (committed)
├── configs/                # YAML configuration (committed)
├── conftest.py
├── core/                   # framework
├── data_storage/           # local price cache (gitignored)
├── docs/                   # documentation
├── outputs/                # backtest outputs (gitignored)
├── portfolio/              # static allocator + state
├── pyproject.toml
├── requirements.txt
├── scripts/                # CLI utilities
├── start.bat / start.ps1   # Windows launchers
├── strategies/             # plug-and-play strategy modules
├── tests/                  # pytest suite
└── ui/                     # Streamlit pages
```

## Python LOC per area

| Area | Lines |
|---|---:|
| `core/` | 5,325 |
| `strategies/` | 1,500 (excluding `_archived`) |
| `ui/` | 2,048 |
| `scripts/` | 1,830 (excluding `_archived`) |
| `tests/` | 952 |
| `portfolio/` | 812 |
| **Total Python (live tree)** | **~12,500** |

## Active strategies after cleanup

| Strategy | Status | LOC |
|---|---|---:|
| `bonds_income` | active | ~440 |
| `passive_equity` | active | ~120 |
| `pattern_finder` | scaffold | ~140 |
| `_examples/dummy_buy_and_hold` | reference | ~70 |
| `_archived/quality_stocks` | archived | (preserved, not counted in live total) |

## Tests passing post-cleanup

`pytest tests/ strategies/ -x` → **78/78 passed** (verified before Phase 4 commit prep).
