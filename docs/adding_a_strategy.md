# Adding a New Strategy

The framework is **plug-and-play** as of Phase 4. Drop a folder under
`strategies/<id>/` with a `strategy.py` and a `config.yaml`, restart the
Streamlit dashboard, and the strategy auto-registers everywhere — Strategies
page, Backtest Runner dropdown, Portfolio Overview opportunistic tab — with
zero code changes to the UI.

This page is the contract. The reference implementations are
`strategies/_examples/dummy_buy_and_hold.py` (simplest possible) and
`strategies/bonds_income/` (realistic example with config + tests + provider
dependency).

---

## 1. Create the subpackage

```
strategies/my_new_strategy/
├── __init__.py          # re-exports the public class (optional)
├── strategy.py          # contains the Strategy subclass
├── config.yaml          # strategy_id, status, parameters
├── README.md            # one-page description (optional but recommended)
└── tests/
    ├── __init__.py
    └── test_smoke.py
```

A minimal `__init__.py`:

```python
from strategies.my_new_strategy.strategy import MyNewStrategy
__all__ = ["MyNewStrategy"]
```

---

## 2. Implement `Strategy`

Imports use the bare-prefix convention (`from core...`, NOT `from quant_lab.core...`):

```python
from __future__ import annotations

from typing import Optional
import pandas as pd

from core.strategy.base import Strategy
from core.strategy.signals import Action, Position, Signal


class MyNewStrategy(Strategy):
    def __init__(self, *, some_param: str = "default") -> None:
        self._strategy_id = "my_new_strategy"
        self._param = some_param

    @property
    def strategy_id(self) -> str:
        return self._strategy_id

    @property
    def universe(self) -> list[str]:
        return ["AAPL", "MSFT"]   # whatever your strategy trades

    def on_init(self, history: pd.DataFrame) -> None:
        # Called once before the main loop
        pass

    def generate_signals(
        self, date: pd.Timestamp, history: pd.DataFrame,
        open_positions: list[Position],
    ) -> list[Signal]:
        # Return Signal(strategy_id=..., instruments=[...], sides=[...],
        #               target_sizes_eur=[...], metadata={...})
        return []

    def manage_positions(
        self, date: pd.Timestamp, history: pd.DataFrame,
        open_positions: list[Position],
    ) -> list[Action]:
        # Return Action(position_id=..., action="close", reason="...")
        return []
```

---

## 3. Create `config.yaml`

```yaml
strategy_id: my_new_strategy
description: "One-line description shown in the UI"
status: scaffold      # scaffold | active | deprecated

# Strategy-specific parameters
my_param: value
```

Status conventions:
- **`scaffold`**: code is in place but not yet validated / activated. Shows as
  🟡 in the UI and is excluded from Backtest Runner dropdown by default.
- **`active`**: validated and ready to run. Shows as 🟢. Appears in dropdowns.
- **`deprecated`**: kept for reference. Shows as ⚫. Excluded from dropdowns.

---

## 4. Assign to a sleeve (optional)

Edit `configs/portfolio.yaml`:

```yaml
sleeves:
  opportunistic:
    strategy_ids: ["my_new_strategy"]
    strategy_weights:
      my_new_strategy: 1.0   # or split among multiple
```

**If you don't add it**, the registry auto-assigns the strategy to the
**opportunistic** sleeve. That's the intended default — opportunistic is
the catch-all for new candidates.

---

## 5. (Recommended) Add a smoke test

```python
# strategies/my_new_strategy/tests/test_smoke.py
from strategies.my_new_strategy import MyNewStrategy

def test_instantiates():
    s = MyNewStrategy()
    assert s.strategy_id == "my_new_strategy"
    assert s.universe   # non-empty
```

Add the class to `tests/test_strategy_interface.py` so the ABC-compliance
suite runs against it.

---

## 6. Restart Streamlit

The registry rescans on each Streamlit process start. After restart:

- **Strategies page** lists the new strategy under the correct sleeve.
- **Backtest Runner dropdown** includes it (if `status: active`).
- **Portfolio Overview opportunistic tab** auto-counts the new strategy.

No edits to UI code required.

---

## 7. Validation checklist (BEFORE flipping to `status: active`)

These are the lessons from Quality Stocks V5 (archived 2026-05-11 — see
`_migration_log/V5_VS_SPY_DECISION.md`). Every active equity strategy must
clear them or stay `scaffold`.

- [ ] **Hypothesis** stated in `README.md` BEFORE running any backtest.
  Why does this strategy have edge? Why now? Why hasn't the market arbitraged
  it away?
- [ ] **Walk-forward validation**: ≥ 5 folds, fixed parameters across folds,
  median OOS Sharpe > 0.2 minimum. Use
  `scripts/run_quality_walk_forward.py` (now archived) as a template — it
  produced 13-fold WF in ~10 min on the FMP cache.
- [ ] **Survivorship correction** if the strategy touches equity indices.
  Without it, results are inflated by 10-30 % (V5 lost the inflation but
  also lost the absolute-return case — make sure your strategy doesn't have
  the opposite problem).
- [ ] **Benchmark comparison**: the strategy must beat a passive alternative
  meaningfully (e.g. SPY for US equity, GBE bond ladder for fixed income).
  Required: annualised alpha > +2 pp **AND** Sharpe delta > +0.15 **AND** the
  alpha is positive in a majority of calendar years.
- [ ] **Bootstrap CI on daily OOS returns** must exclude 0 at 95 %.
- [ ] **Explicit promote-or-archive rule** written before seeing results.
  Resist the salvage loop ("let me tweak one more parameter").
- [ ] **Forward paper-trading** for 3+ months before scaling to live capital.

The Backtest Runner page provides the SPY benchmark overlay (Phase B) — use
it to gate every active strategy.

---

## 8. Why the registry approach matters

The framework's plug-and-play property is only valuable if you adhere to the
file conventions. The registry trusts that:
- `strategy.py` contains exactly **one** primary `Strategy` subclass defined
  in that module (no aliasing through imports).
- `config.yaml` carries `strategy_id` (else folder name is used).
- Folders starting with `_` are off-limits (used for `_archived`, `_examples`,
  `_legacy`).

If a strategy is broken (import error, syntax error), the registry logs a
warning and continues — the UI does not crash. Use `python -c "from
core.strategy.registry import StrategyRegistry; r = StrategyRegistry(); print(r.all())"`
to debug discovery from the CLI.
