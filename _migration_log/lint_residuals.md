# Lint Residuals — pre-v1.0.0

Generated after `ruff format` + `ruff check --select I,E,F,W --fix .` runs.

## Summary

- **Autofixed**: 95 issues (53 lint + 42 import-sort)
- **Manually fixed**: 7 issues (5× F841 unused-var, 1× E741 ambiguous `l`, dead-code block in compare_passive_allocations.py)
- **Residual (intentional, non-blocking)**: 68

## Residual breakdown

| Rule | Count | Why kept |
|------|-------|----------|
| E402 | 49    | Streamlit pages + scripts need `sys.path.insert(0, ...)` BEFORE module imports — otherwise the `core.*` / `strategies.*` packages aren't discoverable. Pattern is documented at the top of every offending file. |
| E501 | 19    | Long lines, mostly long URLs / SQL strings / log-format templates inside docstrings. Cosmetic only. |

## E402 affected files (all with bootstrap pattern)

All `ui/pages/*.py` files plus a handful of scripts. The pattern is:

```python
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
# ---

from core.data.storage import DataStorage   # <-- E402 fires here
```

The bootstrap MUST run before the project imports, so suppressing E402 with a `# noqa` block would just add noise without changing behaviour.

## Decision

E402 and E501 are accepted as residuals. The repo is clean for all import-correctness rules (F-series) and code-quality rules (W-series).
