# bonds_income

**Status**: working (MVP)

**Purpose**: monthly-rebalanced buy-and-hold sovereign bond income strategy. Reads bond data from the Borsa Italiana SQLite DB (via `BorsaItalianaProvider`), ranks by net yield to maturity (after-tax), and holds the top N equal-weighted.

## Logic

- **Universe**: government bonds in EUR (configurable), excluding callables and inflation-linked.
- **Selection**: rank candidates by `net_yield_pa` after applying filters (min yield, max duration, min time to maturity).
- **Rebalance**: monthly (configurable to weekly/quarterly). On rebalance day, close positions no longer in the top N and open positions for new picks.
- **Sizing**: equal weight across N picks.
- **No leverage, no shorting.**

## Config

See `config.yaml`:
- `n_bonds`: number of bonds held simultaneously (default 20)
- `min_yield_pct`: floor on net yield (default 2.0)
- `max_duration_years`: ceiling on years-to-maturity (default 8)
- `rebalance_freq`: `monthly`, `weekly`, `quarterly`

## How to run a backtest

```python
from quant_lab.core.backtest.engine import PortfolioBacktester
from quant_lab.strategies.bonds_income import BondsIncome
from quant_lab.core.data.providers.borsa_italiana_provider import BorsaItalianaProvider

provider = BorsaItalianaProvider(db_path="...")
strat = BondsIncome(bonds_provider=provider, initial_capital_eur=50_000)
# panel must be a wide DataFrame of bond prices indexed by date, columned by ISIN
bt = PortfolioBacktester(strat, panel, initial_capital_eur=50_000)
result = bt.run()
```

## Phase 1 caveats

- **No real historical bond price panel yet.** The strategy can generate
  *current* signals (live mode), but a proper historical backtest
  requires BTP / OAT / Bund price history. Loading that is a Phase 2
  task — populate `data_storage/bonds/historical_prices.parquet` or
  similar.
- Parameters in `config.yaml` are reasonable defaults, not calibrated.

## Phase 2 to-do

- Load BTP/OAT historical price series (likely from yfinance via ticker
  proxies or from a dedicated bond data provider).
- Add coupon accrual to the equity curve.
- Walk-forward over 2008-now to assess robustness.
- Compare against a 60/40 benchmark.
