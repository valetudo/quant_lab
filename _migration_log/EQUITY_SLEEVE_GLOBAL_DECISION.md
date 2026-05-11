# Equity Sleeve: Switch from US-only (CSPX) to Global (VWCE)

## Date
2026-05-11 (effective with v1.1.0)

## Decision
Equity sleeve (30 % of portfolio) changes from:
- **Old**: `CSPX.L` (iShares Core S&P 500 UCITS, 500 USA companies, TER 0.07 %)
- **New**: `VWCE.MI` (Vanguard FTSE All-World UCITS, ~3700 global companies, TER 0.19 %)

ISIN: IE00BK5BQT80. Listed on Borsa Italiana in EUR.

## Rationale

### Why this wasn't questioned earlier
The original choice of S&P 500 (CSPX) was an unexamined default inherited
from the Quantopian-era US-centric backtesting context. Quality Stocks V5
research was framed around the S&P 500 universe, and CSPX was selected as
its passive replacement (Phase 4) without explicit comparison vs global
alternatives — the decision lineage was implicit, not deliberate.

### Why switch to global

1. **Genuine diversification**: VWCE covers 47+ countries vs 1 (USA).
   Includes emerging markets (China, India, Brazil, etc.) which represent
   ~25 % of global GDP and are demographically growing faster than developed.

2. **Valuation context**: As of May 2026, CAPE Shiller is ~35 for USA
   (historically high), ~18 Europe, ~13 emerging. High CAPE statistically
   predicts lower forward returns. Overweighting the expensive geography
   at 30 % of portfolio is a bet that should be justified, not defaulted to.

3. **Historical alternation**: US and ex-US alternate in 10–15 year cycles
   of outperformance. The 2014–2024 US dominance is one cycle, not a
   permanent regime. 1970s, 1980s, and 2000s had ex-US outperformance.

4. **Cost parity**: VWCE TER reduced to 0.19 % in October 2025 (from 0.22 %).
   Difference vs CSPX (0.07 %) is 0.12 pp/yr — small price for true
   diversification on 30 % of portfolio (~€36/yr on €30k position).

5. **Operational simplicity**: Single ETF for global exposure. No need
   for multi-ETF rebalancing (e.g., 70 % CSPX + 20 % EUR equities + 10 % EM)
   that would introduce drift management complexity.

6. **Italian retail accessibility**: VWCE.MI listed on Borsa Italiana in
   EUR, directly purchasable via Fineco / Directa / IBKR without FX conversion.

### Trade-offs accepted

- Slightly higher TER (0.19 % vs 0.07 %, ~€36/yr on €30k position).
- Less historical data in FMP cache (VWCE listed 2019, CSPX listed 2010)
  → solved via `VT` (Vanguard Total World, US-listed equivalent) as backtest proxy.

## Implementation

- `strategies/passive_equity/config.yaml` — `symbol: VWCE.MI`, notes refreshed.
- `strategies/passive_equity/strategy.py` — default symbol fallback updated;
  inline proxy table extended.
- `core/data/storage.py` — `RETAIL_PROXIES` extended with VWCE/VWRL → VT and
  IWDA/SWDA/EUNL → URTH mappings.
- `configs/portfolio.yaml` — equity sleeve notes refreshed.
- `portfolio/state.py` — default fallback symbol updated.
- `ui/pages/1_Portfolio_Overview.py` — equity tab banner + chart switched
  to VWCE/VT.
- `ui/pages/3_Backtest_Runner.py` — `passive_equity` builder uses VWCE.MI.
- `scripts/run_backtests.py` — same.
- Documentation: root `README.md`, `docs/architecture.md`,
  `strategies/passive_equity/README.md`, `CHANGELOG.md`.

CSPX mappings preserved in `RETAIL_PROXIES` and the strategy proxy table
for backward compatibility — anyone on v1.0.0 continues to work; switching
back is a single-line config edit.

## Future considerations

- If geographic tilt becomes desirable (e.g., explicit EM overweight or
  EUR home bias), it can be implemented in the opportunistic sleeve as a
  separate strategy without touching the passive core.
- Bond sleeve remains EUR-denominated (Italian / EU bonds), so global
  equity provides natural currency diversification (~62 % USD exposure
  via VWCE).

## Reversibility

Switching back to CSPX or to any other UCITS equity ETF requires only:

1. Change `symbol` in `strategies/passive_equity/config.yaml`.
2. Restart Streamlit.

The framework's modular design makes this a ~30-second operation.
