# passive_equity

Buy-and-hold a single ETF — the Phase-4 equity sleeve.

| | |
|---|---|
| Sleeve | equity (30 % of portfolio) |
| Primary symbol | `CSPX.L` (iShares Core S&P 500 UCITS) |
| Backtest proxy | `SPY` (when CSPX not in cache; 99 %+ correlated) |
| Rebalance | never |
| Status | `active` |

## Why passive?

Quality Stocks V5 (the previous active equity strategy) was archived on
2026-05-11 after underperforming SPY buy-and-hold by **−4.6 pp/yr** over
13 years OOS. See `_migration_log/V5_VS_SPY_DECISION.md`.

The user's stated criterion: any active strategy in this sleeve must
*significantly outperform* the passive baseline; V5 didn't. So the sleeve
is now the baseline itself.

## What this strategy does

- On the first bar with a valid price, it buys `symbol` (or the retail
  proxy if the configured symbol isn't in the data layer) for the full
  configured capital.
- It never sells.
- It never rebalances.
- Dividends are reinvested automatically via `adj_close`.

## Symbol vs proxy

The default `symbol` is `CSPX.L` — the ETF the user actually buys at the
broker. In backtests, FMP's free/paid tiers don't always carry European
UCITS ETFs, so the strategy and the engine fall back to `SPY` (US-listed,
fully captured by FMP). The S&P 500 underlying is identical; the only
real-world difference for the user is the wrapper / domicile / currency
(USD↔EUR FX is a separate concern handled at the broker level).

The `metadata.used_proxy` flag in the signal records when a proxy was used,
so the audit trail is preserved.

## Files

```
passive_equity/
├── __init__.py
├── strategy.py            # PassiveEquity(Strategy) — ~120 lines
├── config.yaml            # symbol, capital, status
├── tests/test_passive_equity.py
└── README.md
```

## To re-activate an active equity strategy

If a new candidate strategy can demonstrably beat passive SPY, follow the
checklist in `docs/adding_a_strategy.md` — explicitly requiring benchmark
comparison from day 1, not just walk-forward robustness.
