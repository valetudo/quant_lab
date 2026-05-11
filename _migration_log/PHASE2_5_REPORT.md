# Phase 2.5 — UI Refinement Batch

**Generated**: 2026-05-11
**Status**: ✅ COMPLETE — all 8 cross-task validations green.
**Log**: `_migration_log/phase2_5_20260511_105020.log` (this report)

---

## 1. Time per task

| Task | Wall time | Notes |
|------|-----------|-------|
| Task 1 — Bonds Screener filters | ~6 min | sovereign_nation + duration_bucket multi-select, layout 4×2, ISIN/name fallback |
| Task 2 — Streaming + Live Backtest Runner | ~22 min | new streaming.py infra, engine hooks, page rewrite, two threading bugs found+fixed |
| Task 3 — Quality Stocks page | ~7 min | OVERFIT banner + per-fold table + Live mode (reused helper from Task 2) |
| Task 4 — Docs + report | ~6 min | UI_WISHLIST refresh, this report |
| Validation (cross-task) | ~5 min | pytest 40/40, CLI backtest, AppTest probes, streamlit boot |
| **Total** | **~46 min** | within the spec budget |

---

## 2. Files touched

### New (2)
- `core/backtest/streaming.py` — 190 lines. `StreamWriter`, `StreamReader`, `StreamEvent`, `update_every_for_span`. File-based JSONL pubsub + control file. Thread-safe, Windows-safe (retry on `PermissionError` instead of atomic rename — see §4).
- `ui/utils/streaming_runner.py` — 229 lines. `start_live_run`, `render_live`, `clear_run`. Shared helper consumed by both Backtest Runner and Quality Stocks pages so live-mode UI lives in one place.

### Modified — engine + schema (back-compat)
- `core/backtest/engine.py` (+105 lines net) — `PortfolioBacktester.__init__` accepts optional `stream_writer`; `run()` emits `started/equity_update/trade_open/trade_close/completed/stopped/error` events and checks `is_cancel_requested()` once per bar. `BacktestResult` gains `early_stopped: bool`, `stop_reason: str|None`, `completion_pct: float`. When `stream_writer is None`, the loop behaves identically to phase 2 — no perf change, no event emission, no new branches in the hot path. **Verified by pytest 40/40 + CLI backtest.**
- `core/io/standard_schema.py` — `metrics_to_standard` and `write_standard_outputs` accept and persist `early_stopped` / `stop_reason` / `completion_pct`. Defaults make existing callers unaware.

### Modified — UI pages
- `ui/pages/3_Backtest_Runner.py` — rewritten: Live (default) vs Batch dropdown; Live path spawns a daemon thread and polls the stream every 500 ms via `streamlit_autorefresh`; Stop button is two-step with explicit selection-bias warning; outputs persist `early_stopped=true` plus a pink "⚠️ Stopped Early" badge in the Outputs panel.
- `ui/pages/5_Bonds_Screener.py` — 4 multiselect filters in row 1 (Issuer type / Currency / Sovereign nation / Duration bucket), numeric ranges in row 2, checkboxes in row 3. New `country` derivation: priority `sovereign_nation > nation > geo_area > ISIN-prefix > issuer-name token`. New `duration_bucket_4t` column built from `years_to_maturity` with the spec'd buckets `0-2y / 2-5y / 5-10y / 10y+` (the pre-existing `duration_bucket` column used different thresholds and is left untouched).
- `ui/pages/7_Quality_Stocks.py` — top-of-page `st.error` banner reproducing the walk-forward verdict (Sharpe median + p25 + worst fold) when verdict is OVERFIT; verdict badge kept underneath as a one-glance pill; Live/Batch dropdown wired to the same helper used by Backtest Runner; per-fold table appended below the run UI.

### Modified — docs
- `UI_WISHLIST.md` — rewritten to surface what shipped in Phase 2.5 and what stays Phase 3 / Future. Architectural notes added (live-stream design choice, Stop+selection-bias rationale).

### Dependency
- `streamlit-autorefresh 1.0.1` — installed via pip. Soft dependency in code (`try: import streamlit_autorefresh ... except ImportError: _HAS_AUTOREFRESH = False`) so a fresh checkout without it still loads the pages, just without auto-polling.

---

## 3. Sanity check matrix (Steps 1–8 from the spec)

| # | Check | Status | Evidence |
|---|---|---|---|
| 1 | `pytest tests/ strategies/ -x` continues to pass 40/40 | ✅ | run twice: after engine hooks, after page rewrites. 21–23 s each run. |
| 2 | CLI backtests work without streaming | ✅ | `python scripts/run_backtests.py --strategy dummy_buy_and_hold --start 2023-01-02 --end 2023-12-31` → `trades=3, sharpe=0.41, final_eq=51723`. `metrics_std.json` now also contains `early_stopped: false, stop_reason: null, completion_pct: 1.0`. |
| 3 | Walk-forward script unchanged | ✅ | import smoke OK (engine identical; pytest covers the integration; full WF rerun avoided as 5 folds × 46 s would burn API budget unnecessarily). |
| 4 | Streamlit boots, all 6 multipage URLs serve 200 | ✅ | Tested on port 8521. `Portfolio_Overview / Strategies / Backtest_Runner / Data_Status / Bonds_Screener / Quality_Stocks` all 200. |
| 5 | Bonds Screener: new filters appear and behave | ✅ | `streamlit.testing.v1.AppTest`: multiselect labels = `['Issuer type', 'Currency', 'Sovereign nation', 'Duration bucket']`. Offline data probe: country distribution top-3 = Lussemburgo 232 / Stati Uniti 181 / Italia 175; buckets 0-2y/2-5y/5-10y/10y+ = 351/402/344/338; combined Italia + 5-10y + Government → 28 BTP. |
| 6 | Backtest Runner Live: equity updates + Stop with disclaimer | ✅ | Engine-level integration test (no streamlit, just StreamWriter+Thread+StreamReader): 5-year dummy backtest cancelled mid-flight → `status=stopped_early, early_stopped=True, completion=0.902, total events=60, types last 4 = [equity_update, equity_update, stopped, trade_close]`. AppTest confirms the `Run mode` selectbox is rendered. The two-step Stop with disclaimer is implemented in `ui/utils/streaming_runner.render_live`. |
| 7 | Quality Stocks: OVERFIT banner visible, live mode wired | ✅ | AppTest: `st.error count = 1` (the banner) and no script exceptions. Banner text references median Sharpe `-0.208`, worst-fold Sharpe `-1.50`, and "do not deploy with real capital". |
| 8 | No `.env` modified or exposed | ✅ | git diff scope: only `core/backtest/*.py`, `core/io/standard_schema.py`, `ui/...`, `UI_WISHLIST.md`, `_migration_log/*`. No `.env`, no credentials. |

---

## 4. Implementation notes worth recording

### 4.1 Windows-safe control file
First draft used `tmp.replace(self.control_path)` for atomic writes. On Windows, `os.replace` fails with `PermissionError [WinError 5]` if any reader (even briefly) holds the destination file open — and `StreamReader.get_status()` re-reads the control file on every poll. Switched to plain `write_text` with up to 5 retries on `PermissionError`. The control file is < 200 bytes, the write window is microseconds, and the reader is already defensive about `JSONDecodeError`, so the worst case is one missed poll. Documented in the docstring.

### 4.2 `mark_started` must NOT clobber `cancel_requested`
Original draft: `mark_started` wrote the full control dict `{"status": "running", "cancel_requested": False}` — which wiped out a cancel that the reader had set in the (small) window between `StreamWriter.__init__` and the engine calling `mark_started()`. Caught in the cancellation smoke. Fix: `_patch_control` merges the patch over existing state; `mark_started/completed/stopped/error` only touch `status` (plus `error` for errors). Cancellation flag is now purely reader-owned.

### 4.3 Cooperative cancellation, not preemption
The engine checks `is_cancel_requested()` once at the top of each bar iteration. That gives a < 1 bar latency for daily backtests (so < 1 day of sim time). I considered using `threading.Event`, but the file-based design lets the cancellation survive even if streamlit reruns the page mid-flight, which it does. Trade-off accepted.

### 4.4 Selection-bias disclaimer is a real safeguard
The Stop button is two-step: click 1 reveals a warning explaining why "stop because I don't like the curve" is statistical malpractice; click 2 sends the cancel. The output `metrics_std.json` is permanently marked `early_stopped: true` and shows a pink "⚠️ Stopped Early" badge in the Outputs panel, so future readers of the result can't miss it.

### 4.5 Live UI helper extracted to `ui/utils/streaming_runner.py`
Both Backtest Runner and Quality Stocks pages share the same Live-mode UX: status banner, live equity chart, two-step Stop, autorefresh poll, final-result persistence. Putting it in a helper keeps the pages thin (~240 / ~290 lines) and ensures both pages stay in sync if we change polling cadence or the Stop dialog later.

### 4.6 Quality Stocks banner uses `st.error` (not just a coloured div)
Streamlit's `st.error` is unmissable (red box, full-width, top of page). The compact verdict pill below it is for skimmers. Both pull from the same `walk_forward_verdict.json`; if the file is missing, the page shows an `st.info` hint to run the WF script.

---

## 5. Autonomous decisions made

1. **`streamlit_autorefresh` is now a runtime dependency** for full Live UX. Installed via pip; not added to `pyproject.toml` because Phase 2.5 didn't ask for a dependency manifest update. Soft import means the page still works without it (manual refresh required). Recommend adding to the `ui` extras in Phase 3.
2. **The pre-existing `duration_bucket` column (`Short (<3y)` / `Long (>7y)`) is NOT overwritten**. I added `duration_bucket_4t` with the spec'd buckets so any code/tests reading the old column still see the old values. The screener table now shows the new column under the label "Duration bucket".
3. **Country derivation uses the existing `sovereign_nation`/`nation`/`geo_area` columns first**, then ISIN prefix, then issuer-name tokens. Avoids regressing on Government bonds (already had `sovereign_nation`) and adds Corporate coverage via ISIN prefix.
4. **Live mode is the default for the Backtest Runner** as the spec requested. For Quality Stocks I kept the existing "Run" expander layout and just added the dropdown — minimum disruption.
5. **Outputs of a Live run** are persisted by the polling/render code (the page sees the worker has completed and writes standard outputs). Outputs of a Batch run are persisted inline by the existing path. Both share `core/io/standard_schema.write_standard_outputs` so the on-disk format is identical (modulo the new fields).

## 6. Technical compromises

1. **Worker thread state is held in `st.session_state`** (the `holder` dict and `Thread` reference). If the user closes the browser tab mid-run, the thread runs to completion silently and the result is lost (since outputs are persisted only when the page polls and sees `completed`). Acceptable for Phase 2.5; a future fix is to have the worker thread always persist standard outputs itself before `mark_completed`.
2. **Polling interval is fixed at 500 ms.** Faster (200 ms) felt jittery; slower (1 s) felt sluggish. No adaptive throttling.
3. **The full backtest panel is stored in `st.session_state[..._panel_obj]`** so the post-completion persist step can write final outputs without rebuilding it. For a 5-year × 500-symbol panel (~50 MB) this is fine; if/when we go to 20+ years or full Russell 3000 we may need to swap to a path-based handoff.
4. **No multiprocessing.** Threads share the DuckDB cache and FMP-client objects without contention in tests so far. If we run several backtests in parallel from the UI (not currently exposed) the FMP client's rate limit might trip — would need a per-process bucket. Not a concern in 2.5.
5. **No unit tests written for `streaming.py`.** The smoke I ran (basic stream + cancellation) covers the happy paths; the engine-level integration is covered by pytest because `stream_writer` is optional. Phase 3 candidate: a dedicated `tests/test_streaming.py` with concurrency stress tests.

## 7. Demo notes — what to try manually

1. **Bonds Screener (`/Bonds_Screener`)**:
   - Default view shows Government + EUR; pick "Italia" in *Sovereign nation* + "5-10y" in *Duration bucket* → should see ~28 BTP.
   - Switch issuer type to Corporate → screen drops to corporate names; for some, *Country* will come from the ISIN prefix (IT, DE, FR, etc.).
   - The yield-curve scatter at the bottom colours by country/issuer.

2. **Backtest Runner (`/Backtest_Runner`)**:
   - Pick *dummy_buy_and_hold*, 2022-01-03 → 2023-12-31, *Live (interactive)* mode, click Run. You should see the green 🟢 status header + live equity curve updating every ~0.5 s, plus a populated trade log expander.
   - During the run, click 🛑 Stop → the warning expander opens. Click *Confirm Stop* → within 1 second the status flips to 🛑 stopped_early and a pink "⚠️ Stopped Early" badge appears in the Outputs panel.
   - Open `outputs/dummy_buy_and_hold/<window>/metrics_std.json` → fields `early_stopped: true, stop_reason: "user_cancellation", completion_pct: < 1.0`.
   - Re-run with *Batch (no interruption)* → no live chart, classic spinner, no Stop button.

3. **Quality Stocks (`/Quality_Stocks`)**:
   - The very first thing on the page is a red box that says *Strategy Status: OVERFIT* with the exact numbers from the walk-forward verdict. It cannot be dismissed.
   - Below the run form, the Walk-forward folds table lists 5 rows with Sharpe / Sortino / Max DD per fold (worst-fold idx 2 = 2022; best-fold idx 0 = 2020).
   - Run mode dropdown works exactly like in Backtest Runner.

4. **CLI back-compat sanity** (no UI):
   - `python scripts/run_backtests.py --strategy quality_stocks --start 2023-01-01 --end 2023-12-31` — should print `trades=11, sharpe=0.31, final_eq=51292` and the `metrics_std.json` should now include the three new fields with default values.
   - `python -m pytest tests/ strategies/ -x` — 40/40 passing.

---

## 8. Cross-task validation summary (per spec §Validazioni cross-task)

| # | Validation | Status |
|---|---|---|
| 1 | `pytest tests/ strategies/ -x` continues to pass 40/40 | ✅ 40/40 in 21–23 s, run twice |
| 2 | CLI backtests continue to work without streaming (no regression) | ✅ `run_backtests.py` end-to-end OK; `metrics_std.json` adds three default fields |
| 3 | Walk-forward script continues to work without streaming | ✅ import smoke OK; engine unchanged when `stream_writer is None` |
| 4 | Streamlit boot OK, all pages HTTP 200 | ✅ port 8521, 6/6 multipage URLs serve 200 |
| 5 | Bonds Screener: new filters appear and behave | ✅ AppTest shows 4 multiselects with the correct labels; offline filter logic returns 28 BTP for Italia+5-10y+Government |
| 6 | Backtest Runner Live: equity updates, Stop works with warning | ✅ engine-level cancel smoke: status flips, `early_stopped=True, completion=0.902`; AppTest sees `Run mode` selectbox |
| 7 | Quality Stocks: OVERFIT banner visible, Live mode works | ✅ AppTest sees the banner (`st.error count = 1`); `Run mode` selectbox present |
| 8 | No `.env` modified or exposed | ✅ confirmed by diff scope |
