# Strategie archiviate

Tracker per strategie sviluppate e poi archiviate, con motivazione e link al codice originale (in `_backups/`).

## pair_trading_ITA (archiviata dopo iter6)

**Periodo di sviluppo**: ~6 mesi, 6 iterazioni, 16+ run di backtest.

**Risultato finale**:
- Walk-forward verdict: **OVERFIT** (Sharpe in-sample 0.42, OOS mediano 0.215, p25 −0.21)
- Geographic OOS test: solo l'universo FR ha mostrato Sharpe positivo (0.55 in-sample)
- Sharpe forward stimato per variante FR: 0.20–0.30 dopo costi reali

**Motivo archiviazione**: anche la variante FR (l'unica positiva) non giustifica la complessità di mantenimento nel framework multi-strategy. Edge marginale e non strutturale.

**Lezioni metodologiche conservate** (migrate in `core/`):
- Walk-forward dall'inizio, non alla fine
- Schema dati standardizzato → `core/io/standard_schema.py`
- Slippage non-lineare `sqrt_impact` → `core/backtest/costs.py`
- Attribution analysis per filtri → `core/analytics/attribution.py`

**Codice originale**: `_backups/pre_quant_lab_20260510_235842/pair_trading_ITA/`
(non sotto git nella locazione `trading_systems/pair_trading_ITA/` originale).

## pattern_finder (parcheggiata, non archiviata)

**Status**: sviluppo sospeso per scelta, sarà riconsiderato dopo che `bonds_income` e `quality_stocks` saranno tradabili.

**Repo originale**: https://github.com/valetudo/pattern_finder

**Codice**: NON migrato in fase 1, resta nel repo originale per futura integrazione (fase 3+).

## Quality Stocks (in scaffolding, target Phase 2)

**Status**: scaffold creato in `strategies/quality_stocks/`, implementazione rinviata.

**Reference**: 5 file Quantopian originali in `docs/quantopian_archive/` (vuota oggi, da popolare quando il codice di riferimento è recuperato).

**Piano Phase 2**: factor model su ROIC, debt/equity, gross margin stability, accruals. Vedi `strategies/quality_stocks/README.md` per dettaglio.
