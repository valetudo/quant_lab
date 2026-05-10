# Adding a strategy

Template walkthrough — implementing the `Strategy` ABC.

## 1. Create the subpackage

```
strategies/my_strategy/
├── __init__.py
├── strategy.py         # subclass Strategy here
├── config.yaml         # parameters
├── tests/__init__.py
└── README.md
```

## 2. Subclass `Strategy`

```python
from quant_lab.core.strategy.base import Strategy
from quant_lab.core.strategy.signals import Action, Position, Signal
import pandas as pd

class MyStrategy(Strategy):
    def __init__(self, ..., strategy_id: str = "my_strategy"):
        self._strategy_id = strategy_id

    @property
    def strategy_id(self) -> str: return self._strategy_id

    @property
    def universe(self) -> list[str]: return [...]

    def on_init(self, history: pd.DataFrame) -> None: ...

    def generate_signals(self, date, history, open_positions) -> list[Signal]:
        # Return Signal(strategy_id=..., instruments=[...], sides=[...],
        #               target_sizes_eur=[...], metadata={...})
        return []

    def manage_positions(self, date, history, open_positions) -> list[Action]:
        # Return Action(position_id=..., action="close", reason="...")
        return []
```

The reference implementation is `strategies/_examples/dummy_buy_and_hold.py` — it's the simplest possible `Strategy` and is used as the engine smoke-test fixture.

## 3. Wire it into the UI

Add an entry to `ui/pages/2_Strategies.py` (the ENTRIES list) and to the dropdown in `ui/pages/3_Backtest_Runner.py` if you want a Run button.

## 4. Add a smoke test

```python
# strategies/my_strategy/tests/test_smoke.py
from quant_lab.strategies.my_strategy import MyStrategy

def test_instantiates():
    strat = MyStrategy(...)
    assert strat.strategy_id == "my_strategy"
```

## 5. Run the validation suite

```bash
pytest tests/test_strategy_interface.py -k MyStrategy
pytest strategies/my_strategy/tests/
```

The `tests/test_strategy_interface.py` suite auto-validates that every concrete `Strategy` correctly implements the ABC — add your class to the loop there.

## Sizing conventions

- `target_sizes_eur` is EUR notional per leg (signed by `sides`).
- Engine clips proportionally if cash insufficient.
- For multi-leg (e.g. pairs), each leg appears in the same `Signal`.
