"""Pre-flight check #2: ping FMP API.

- /stable/profile?symbol=AAPL must respond 200 with a profile dict.
- /stable/key-metrics-ttm must NOT 403 (premium check).

Never prints the key — only masked.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# --- bootstrap ---
_REPO_ROOT = Path(__file__).resolve().parents[1]
_PARENT = _REPO_ROOT.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))
# ---

from dotenv import load_dotenv
import requests


def mask(key: str) -> str:
    if not key or len(key) < 7:
        return "***"
    return f"{key[:3]}...{key[-3:]}"


def main() -> int:
    load_dotenv(_REPO_ROOT / ".env")
    key = os.getenv("FMP_API_KEY")
    if not key:
        print("FAILED  FMP_API_KEY not set", file=sys.stderr)
        return 1

    base = "https://financialmodelingprep.com/stable"

    # Test 1: basic profile endpoint
    url = f"{base}/profile?symbol=AAPL&apikey={key}"
    try:
        r = requests.get(url, timeout=15)
    except Exception as e:
        print(f"FAILED  network error: {e}", file=sys.stderr)
        return 1

    # Always strip the apikey from any echoed URL
    safe_url = url.replace(key, mask(key))

    if r.status_code != 200:
        print(f"FAILED  HTTP {r.status_code} on {safe_url}", file=sys.stderr)
        print(f"        body: {r.text[:200]}", file=sys.stderr)
        return 1

    data = r.json() if r.text else None
    if not data or not isinstance(data, list) or "symbol" not in (data[0] if data else {}):
        print(f"FAILED  unexpected payload shape from /profile: {str(data)[:300]}", file=sys.stderr)
        return 1
    price = data[0].get("price")
    print(f"OK      /profile AAPL -> ${price}")

    # Test 2: premium endpoint (key-metrics-ttm)
    url2 = f"{base}/key-metrics-ttm?symbol=AAPL&apikey={key}"
    r2 = requests.get(url2, timeout=15)
    if r2.status_code == 403 or "Premium" in r2.text:
        print(f"FAILED  premium endpoint blocked (HTTP {r2.status_code}). "
              "Subscription may not be active.", file=sys.stderr)
        print(f"        body: {r2.text[:200]}", file=sys.stderr)
        return 1
    if r2.status_code != 200:
        print(f"FAILED  HTTP {r2.status_code} on /key-metrics-ttm", file=sys.stderr)
        return 1
    km = r2.json()
    if not km or not isinstance(km, list):
        print(f"FAILED  unexpected payload from /key-metrics-ttm: {str(km)[:300]}", file=sys.stderr)
        return 1
    roic_field = next((f for f in km[0].keys() if "roic" in f.lower()), None)
    print(f"OK      /key-metrics-ttm AAPL accessible (roic-like field: {roic_field})")
    print(f"OK      premium plan active. Using key {mask(key)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
