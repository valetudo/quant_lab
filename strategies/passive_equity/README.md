# passive_equity

Buy-and-hold a single ETF — the Phase-4 equity sleeve (revised in v1.1.0).

| | |
|---|---|
| Sleeve | equity (30 % of portfolio) |
| Primary symbol | `VWCE.MI` (Vanguard FTSE All-World UCITS, ISIN IE00BK5BQT80) |
| Backtest proxy | `VT` (US-listed FTSE All-World — same index, longer history) |
| Rebalance | never |
| Status | `active` |

## Why passive?

Quality Stocks V5 (the previous active equity strategy) was archived on
2026-05-11 after underperforming SPY buy-and-hold by **−4.6 pp/yr** over
13 years OOS. See `_migration_log/V5_VS_SPY_DECISION.md`.

The user's stated criterion: any active strategy in this sleeve must
*significantly outperform* the passive baseline; V5 didn't. So the sleeve
is now the baseline itself.

## Why VWCE (global) instead of CSPX (S&P 500)?

v1.1.0 (May 2026): switched from `CSPX.L` to `VWCE.MI`.

The original CSPX choice was an unexamined default inherited from the
Quantopian-era US-centric backtesting context. VWCE provides:

- **True global diversification** — ~3700 holdings across 47+ countries,
  developed + emerging markets (~62% USA / ~38% rest of world).
- **TER 0.19 %** — reduced from 0.22 % in October 2025; competitive vs CSPX's 0.07 %.
- **Accumulating** — Italian tax efficiency: dividends reinvested without
  the 26 % distribution drag.
- **Borsa Italiana in EUR** — no FX conversion needed for retail purchase.
- **Vanguard structure** — low-cost, transparent, AUM €37 B+ (zero closure risk).

Full rationale: `_migration_log/EQUITY_SLEEVE_GLOBAL_DECISION.md`.

## What this strategy does

- On the first bar with a valid price, it buys `symbol` (or the retail
  proxy if the configured symbol isn't in the data layer) for the full
  configured capital.
- It never sells.
- It never rebalances.
- Dividends are reinvested automatically via `adj_close`.

## Symbol vs proxy

The default `symbol` is `VWCE.MI` — the ETF the user actually buys at the
broker. In backtests, FMP's coverage of European UCITS ETFs is patchy and
VWCE itself only listed in 2019, so the strategy and the engine fall back
to `VT` (Vanguard Total World, US-listed) which tracks the same FTSE
All-World index with longer history.

Pre-v1.1.0 used `CSPX.L` with `SPY` as the proxy — both still wired in
`DataStorage.RETAIL_PROXIES` for backward compatibility.

The `metadata.used_proxy` flag in the signal records when a proxy was used,
so the audit trail is preserved.

## Files

```
passive_equity/
├── __init__.py
├── strategy.py            # PassiveEquity(Strategy) — ~140 lines
├── config.yaml            # symbol, capital, status
├── tests/test_passive_equity.py
└── README.md
```

## To re-activate an active equity strategy

If a new candidate strategy can demonstrably beat passive global equity
(VWCE / VT), follow the checklist in `docs/adding_a_strategy.md` —
explicitly requiring benchmark comparison from day 1, not just
walk-forward robustness.
