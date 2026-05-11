"""Pre-flight check #1: verify FMP_API_KEY is accessible via python-dotenv.

Does NOT read .env directly — only loads it through dotenv and checks the
env var. Never logs the full key — always masks first 3 + last 3 chars.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# --- bootstrap ---
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# ---

from dotenv import load_dotenv


def mask(key: str) -> str:
    if not key or len(key) < 7:
        return "***"
    return f"{key[:3]}...{key[-3:]}"


def main() -> int:
    # Load .env from project root (does not echo contents anywhere)
    env_path = _REPO_ROOT / ".env"
    load_dotenv(env_path)

    key = os.getenv("FMP_API_KEY")
    if not key:
        print("FAILED  FMP_API_KEY not found.", file=sys.stderr)
        print(f"        Looked for {env_path}", file=sys.stderr)
        print("        Create .env with: FMP_API_KEY=<your_key>", file=sys.stderr)
        return 1
    print(f"OK      FMP_API_KEY found (length: {len(key)}, masked: {mask(key)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
