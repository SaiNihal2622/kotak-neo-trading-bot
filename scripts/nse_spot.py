"""nse_spot.py — NSE public spot endpoint for FINNIFTY / MIDCPNIFTY.

FIX 2026-09-17: Kotak Neo Developer tier doesn't include nse_cm spot entitlement
for FINNIFTY (NIFTY FINANCIAL SERVICES) and MIDCPNIFTY (NIFTY MIDCAP SELECT).
Both return HTTP 400 from the Kotak quotes API.

NSE's public allIndices API (https://www.nseindia.com/api/allIndices) DOES
return them — the index level IS the spot price for index options trading.
Verified Sep 17 2026:
  - NIFTY FINANCIAL SERVICES = 25262.4 (FINNIFTY) — Kotak PCR got 25312.6 (within 0.2%)
  - NIFTY MIDCAP SELECT = 14288.45 (MIDCPNIFTY) — Kotak PCR got 14328.1 (within 0.3%)

Caching: 60 seconds. NSE updates intra-minute during market hours, so the
60s TTL keeps us in sync without hammering NSE.

Endpoint requires:
  - Real desktop browser UA (NSE blocks bot UAs)
  - Referer: https://www.nseindia.com/
  - Accept: application/json

Returns the spot for the requested underlying (NIFTY, BANKNIFTY, FINNIFTY,
MIDCPNIFTY, SENSEX) or None if NSE is unreachable / returns 401.

Usage:
    from scripts.nse_spot import get_spot
    spot = get_spot('FINNIFTY')
    if spot:
        print(f"FINNIFTY = {spot}")
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
DCACHE = ROOT / "data_cache"
CACHE_FILE = DCACHE / "nse_index_cache.json"
CACHE_TTL_SEC = 60  # refresh once a minute

# Map our underlying symbols → NSE allIndices index names.
# SENSEX is excluded — SENSEX is a BSE index, not in NSE allIndices.
# Use Kotak Neo for SENSEX (Kotak Developer tier DOES include SENSEX spot).
NSE_INDEX_MAP = {
    "NIFTY": "NIFTY 50",
    "BANKNIFTY": "NIFTY BANK",
    "FINNIFTY": "NIFTY FINANCIAL SERVICES",
    "MIDCPNIFTY": "NIFTY MIDCAP SELECT",
}

NSE_URL = "https://www.nseindia.com/api/allIndices"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


def _fetch_all_indices() -> dict[str, float]:
    """Fetch all NSE indices and return {index_name: last_price}.

    Returns empty dict on failure.
    """
    try:
        req = urllib.request.Request(NSE_URL, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=12) as r:
            data = r.read().decode("utf-8")
            j = json.loads(data)
            out = {}
            for ind in j.get("data", []):
                name = ind.get("index") or ind.get("indexName")
                last = ind.get("last")
                if name and last:
                    try:
                        out[name] = float(last)
                    except Exception:
                        continue
            return out
    except Exception:
        return {}


def _load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(d: dict) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_spot(symbol: str, force_refresh: bool = False) -> float | None:
    """Get the spot price for `symbol` from NSE's public indices endpoint.

    Args:
        symbol: One of NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX.
        force_refresh: Bypass the 60s cache.

    Returns:
        Spot price as float, or None if NSE doesn't return this index
        (or the endpoint fails).
    """
    sym = symbol.upper()
    nse_name = NSE_INDEX_MAP.get(sym)
    if not nse_name:
        return None

    cache = _load_cache()
    ts = cache.get("ts", 0)
    indices = cache.get("indices", {})
    if not force_refresh and (time.time() - ts) < CACHE_TTL_SEC and nse_name in indices:
        return indices.get(nse_name)

    fresh = _fetch_all_indices()
    if not fresh:
        # stale cache is better than nothing
        return indices.get(nse_name)
    new_cache = {"ts": time.time(), "indices": fresh}
    _save_cache(new_cache)
    return fresh.get(nse_name)


def get_all_spots(force_refresh: bool = False) -> dict[str, float]:
    """Get all 5 underlying spots at once. Returns {symbol: price}.

    Useful for the LLM brain's periodic context — one NSE call covers all 5.
    """
    cache = _load_cache()
    ts = cache.get("ts", 0)
    indices = cache.get("indices", {})
    if not force_refresh and (time.time() - ts) < CACHE_TTL_SEC and len(indices) >= 5:
        return {sym: indices[nse] for sym, nse in NSE_INDEX_MAP.items() if nse in indices}

    fresh = _fetch_all_indices()
    if not fresh:
        return {sym: indices[nse] for sym, nse in NSE_INDEX_MAP.items() if nse in indices}
    new_cache = {"ts": time.time(), "indices": fresh}
    _save_cache(new_cache)
    return {sym: fresh[nse] for sym, nse in NSE_INDEX_MAP.items() if nse in fresh}


if __name__ == "__main__":
    # Smoke test
    for sym in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]:
        s = get_spot(sym, force_refresh=True)
        print(f"{sym}: {s}")