# Security Audit Report — pre-v1.0.0

**Date**: 2026-05-11
**Scope**: full repo, live tree (`_archived/` and `_backups/` excluded from active path edits, but scanned for credentials).

## Credentials check

### Hardcoded API keys / tokens
- ✅ **No** API keys / tokens / passwords found in the live tree.
- ✅ FMP key is read from `os.environ["FMP_API_KEY"]` via `python-dotenv` loading `.env` (which is gitignored).
- ✅ False positive: `scripts/_archived/build_quality_refinement_comparison.py` matched `sk-` pattern but only because the text `risk-control` appears in a comment.

### Past chat-exposure check
- ⚠️ **Minor exposure remediation**: `_migration_log/PHASE2_FIX_REPORT.md` contained a *masked* form of the FMP key (`fXQ...Z4r`, 3-char prefix + 3-char suffix). Even though the masker only showed 6 of 32 characters, the combination could theoretically narrow brute-forcing. **Sanitised** to `***...***`.
- ✅ Other `*...*` masked patterns in phase reports do not reference key material (they're shell elision, e.g. `samples/...`).

### `.env` handling
- ✅ `.env` is in `.gitignore` (3 distinct rules, deliberate redundancy).
- ✅ `.env` has never been committed in this repo's history (`git log --all -- .env` returns nothing).
- ✅ `.env.example` template added with placeholder values — see Task 4.

## Path hardcoding

### Personal paths in live tree
Three files had hardcoded `G:/Il mio Drive/__NUOVA_STRUTTURA_DOCUMENTI/...` paths:

| File | Original behaviour | Fix |
|---|---|---|
| `configs/global.yaml` | Hardcoded `data_storage_path` + `bonds_db_path` to the author's Google Drive | Changed all three path fields to `null`; defaults computed at runtime: `data_storage_path` → `<repo>/data_storage`, `bonds_db_path` → `<data_storage>/bonds/bonds.db`. **Override via env vars** `QUANT_LAB_DATA_PATH` / `QUANT_LAB_BONDS_DB_PATH`. |
| `scripts/migrate_bonds_db.py` | `DEFAULT_SOURCE` hardcoded to Google Drive | Now defaults to `<repo>/../bonds/bonds.db` (sibling layout), overridable via env `QUANT_LAB_BONDS_SOURCE` or `--source` CLI flag. |
| `strategies/pattern_finder/config.yaml` | `pattern_finder_path` hardcoded to Google Drive | Now relative `../pattern_finder` (recommended sibling layout), documented in the README. |

### Verification post-fix
```bash
# Live tree (excluding _archived, _migration_log, _backups, .venv, .git):
grep -rl 'G:.Il mio Drive\|__NUOVA_STRUTTURA\|C:.Users.Beppe' \
  --include='*.py' --include='*.yaml' --include='*.toml' \
  --include='*.bat' --include='*.ps1' --include='*.json'
# → no matches
```

### Env-override smoke test
```python
os.environ['QUANT_LAB_DATA_PATH'] = '/tmp/test_override'
s = DataStorage.from_config(load_global_config())
assert s.data_storage_path == Path('/tmp/test_override')   # ✓
```

### Historical phase reports
`_migration_log/*.md` contains the original paths (they're historical records of where files lived during development). **Not sanitised** — those are write-once reports, modifying them would be revisionism. The path strings there are not security-sensitive (they reveal directory layout but not credentials).

## Files reviewed

- **`.py`**: 88 (live tree, excluding `_archived/`)
- **`.yaml`**: 9
- **`.toml`**: 1 (`pyproject.toml`)
- **`.md`**: 22 (live tree)
- **`.json`**: 2 active configs (rest in `outputs/` are generated)
- **Shell scripts**: 2 (`start.bat`, `start.ps1`)

## Outstanding non-issues

- `_migration_log/V5_VS_SPY_DECISION.md` and friends quote past CAGR / Sharpe figures — these are public-domain numbers, not secrets.
- `data_storage/cache/fmp_cache.duckdb` contains 17 years of S&P 500 price + fundamental data fetched from FMP. **Gitignored** so it never reaches the public repo. Personal — the FMP licence allows storage but not redistribution; the gitignore protects against accidental redistribution.

## Result

🟢 **Clean for v1.0.0 push.** No credentials, no personal paths in the committed tree. `.env` template ships; actual `.env` stays local.
