# Pattern Finder (Scaffolded, not yet active)

This is an **adapter** for the external
[pattern_finder](https://github.com/valetudo/pattern_finder) repo, exposed
to the Quant Lab framework as a `Strategy` subclass.

**Current status**: `scaffold` — registers in the auto-discovery registry,
shows up in the UI as "🟡 scaffold", and returns no signals.

## To activate

### 1. Clone external repo

```bash
cd "G:/Il mio Drive/__NUOVA_STRUTTURA_DOCUMENTI/02_FINANZE/trading_systems"
git clone https://github.com/valetudo/pattern_finder.git
```

The default `pattern_finder_path` in `config.yaml` points to that location.
Adjust if you clone elsewhere.

### 2. Install dependencies

The external repo brings its own stack (torch, lightgbm, hmmlearn,
dtaidistance, faiss-cpu, etc.). Install them into the same Python env
running Streamlit, or vendorise them into a side env if conflicts arise.

### 3. Implement signal translation

Fill in the `TODO` markers in `strategy.py`:

| Method | What to do |
|---|---|
| `on_init` | Forward to `self._runner.on_init(history)` if the runner has one |
| `generate_signals` | Call the runner's entry-point with the current date + history slice, translate each external "signal" into a Quant Lab `Signal` with the correct metadata (pattern_id, score, forward_window_days) |
| `manage_positions` | Implement the triple-barrier exit logic: for each open position whose entry-time + forward-window has elapsed (or that has hit an upper/lower price barrier), emit `Action(action="close")` |

### 4. Validate

Required before flipping to `status: active`:

- [ ] Walk-forward ≥ 5 folds, median OOS Sharpe > 0.2
- [ ] Benchmark comparison (vs SPY for US equity patterns) — annualised
      alpha > +2 pp AND Sharpe delta > +0.15
- [ ] Bootstrap 95 % CI on daily OOS returns excludes 0
- [ ] Promote-or-archive rule written BEFORE seeing results

See `docs/adding_a_strategy.md` for the full validation checklist and
`_migration_log/V5_VS_SPY_DECISION.md` for what happens when an active
strategy fails the benchmark gate (it gets archived — same will apply to
Pattern Finder if it doesn't clear the bar).

### 5. Flip status

```yaml
# config.yaml
status: active
```

Restart Streamlit. The adapter now invokes the external runner.

## What the adapter inherits from the framework

By being a `Strategy` subclass, Pattern Finder gets for free:

- **Auto-registration** via `StrategyRegistry`
- **Live equity curve** in Backtest Runner (Phase 2.5)
- **SPY benchmark overlay** automatically (Phase B)
- **Walk-forward infrastructure**
- **Portfolio Overview opportunistic-sleeve tracking** (Phase 4)

The adapter pattern means the external repo can iterate independently
without touching Quant Lab code.
