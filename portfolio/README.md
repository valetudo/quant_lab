# portfolio

**Status**: scaffold

**Purpose**: aggregate the outputs of N strategies into a unified portfolio view (capital allocation, equity combination, attribution).

The standard outputs from each strategy (`trades_std.csv`, `equity_std.csv`, `metrics_std.json`) are written by `core.io.write_standard_outputs`. This package consumes them.

- `allocator.py` — load fractional capital allocation from YAML.
- `aggregator.py` — combine multi-strategy equity curves.
- `reporting.py` — single-file summary report.

Full implementation lands in Phase 2 once at least two strategies are working.
