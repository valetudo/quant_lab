# bonds.db data gaps — handling in the Ladder Builder

The Borsa Italiana scraper output (`bonds.db`) does not carry every column
the LadderBuilder spec assumes. This document records what is missing,
how the builder copes today, and what would unlock stricter behaviour
later.

## Available columns (as of 2026-05-12)

`bonds` table — 1435 rows (964 EUR-denominated, 1177 government, 258 corporate):

| Column | Notes |
|---|---|
| `isin`, `name` | identifier + display label |
| `coupon` | annual coupon in **%** (we convert to decimal `coupon_rate`) |
| `maturity_date` | TEXT date, parsed to Timestamp |
| `currency` | 21 currencies; only EUR retained for the ladder |
| `category` | compound string, e.g. `titoli_di_stato_esteri__fixed__germania` |
| `tipologia` | high-level type (`Titoli Di Stato Italiani`, `Corporate`, …) |
| `nation` | Italian nation label (`Italia`, `Germania`, …); 79 rows are NULL |
| `issuer_type` | `Government` / `Corporate` |
| `geo_area` | usually mirrors `nation` |
| `first_seen` / `last_seen` / `is_active` | scraper metadata |

`bond_prices` table — flat snapshot, only 639 rows (one per bond at most).
No daily history → no volume series.

The `BorsaItalianaProvider` (`enrich=True`) computes on top:
- `latest_price`, `latest_price_date` (NaN for ~55 % of bonds — no recent scrape)
- `years_to_maturity`, `duration_bucket`
- `inflation_linked` (name-pattern match)
- `is_callable` (name-pattern match)
- `sovereign_nation`
- `net_yield_pa` (% units, NaN where price missing — affects 797/1435 rows)

## Spec columns *not* in the DB

| Column | Builder behaviour |
|---|---|
| `issuer` (corporate issuer name) | Parsed by `parse_issuer()` in `core.data.bonds_universe`: governments → country, corporates → first 2 non-digit tokens of `name`. Crude but stable as a concentration key. |
| `rating` (S&P / Moody / Fitch per bond) | None per-row in the DB. We fall back to a hard-coded `SOVEREIGN_RATING` table for government bonds (S&P 2026 Q1 long-term FC). **Corporates have no rating → all corporate ratings show as `NR` (score 99) and would fail any rating filter.** Currently we keep corporate bonds in the universe regardless (no per-row rating) and rely on the `is_subordinated` pattern filter to drop the truly-risky ones; the `corp_min_rating` filter only takes effect after a per-bond rating data feed lands. |
| `rating_score` | Derived from the above, lower = better. |
| `is_subordinated` | Pattern match on `name`: `SUB`, `SUBORD`, `AT1`, `PERP`, `TIER 1`, `TIER 2`. Conservative — over-excludes a handful of senior notes whose marketing name contains "TIER", which is acceptable. |
| `is_callable`, `first_call_date` | `is_callable` already provided by the underlying enricher via name pattern. No `first_call_date` → we drop **any** callable bond unconditionally (conservative). The `corp_exclude_callable_within_years` config knob has no effect on the lookahead window for now. |
| `lot_size_eur` | Defaulted to €1000 face value. Correct for nearly all Italian retail-listed EUR bonds. |
| `coupon_frequency` | Defaulted to 1 (annual). Many real-world EUR bonds pay semi-annual; cash-flow projection therefore under-estimates the cadence (the *aggregate* coupon flow is correct, only the per-event spacing is off). |
| `daily_volume_30d_avg` | Not available. The `foreign_min_daily_volume_eur` filter is silently skipped — the LadderBuilder logs this implicitly by never raising the `foreign_low_liquidity` skip reason. |
| `yield_net` | Aliased from `net_yield_pa` and converted % → decimal in the loader. |

## Rows dropped before ranking

Starting from 1435 raw rows, the universe loader drops (in this order):
1. Non-EUR (471 rows)
2. Already matured (a handful)
3. Subordinated by name pattern
4. Callable
5. Missing `latest_price` (≈ 55 % of the rest — these have no current quote, so we cannot size a lot in EUR)

After all filters, ≈ 580 EUR bonds remain available to the builder.

## What unlocks stricter behaviour later

1. **Per-bond rating data feed** — would let `corp_min_rating` actually
   gate the corporate ranking. Sources: ECB FRA rated-issuer list,
   Bloomberg, ICE Index Services. Without it, corporate filtering is
   limited to the name-pattern exclusions.
2. **Daily price + volume history** — would let `foreign_min_daily_volume_eur`
   actually fire, instead of being silently skipped. Sources: MOT/EuroTLX
   end-of-day feeds.
3. **First-call schedule** — would let `corp_exclude_callable_within_years`
   be selective. Without it, *all* callables are dropped today.
4. **Coupon frequency** — would refine the cash-flow timeline. Without
   it, semi-annual coupons appear at annual cadence.

When any of these lands, the `BondsUniverseLoader` and `_select_best_in_category`
filters are already structured to consume them — the changes will be local
to the loader and a few lines of the builder.
