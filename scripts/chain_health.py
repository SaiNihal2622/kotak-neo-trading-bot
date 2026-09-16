"""FIX 2026-09-11 21:00: chain health check + price validation.

ROOT CAUSE of the phantom Rs.3,060 P&L on Sep 11: the NIFTY option chain
had broken PE prices (PE prices going UP as strike goes DOWN — impossible).
The bot's _force_fill_market_like trusted the chain and filled at the wrong
prices, producing fake P&L.

This module provides:
  1. check_chain_health(underlying) — detect broken chains
  2. validate_fill_price(symbol, raw_price, expected_price) — reject phantom prices
  3. bs_estimate(spot, strike, opt_type, days_to_expiry) — Black-Scholes fallback
     when the chain is bad or missing.
"""
from __future__ import annotations
import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent.resolve()
DCACHE = ROOT / "data_cache"

# Sanity range for option prices per underlying (in INR per share).
# Anything below MIN_OPTION_PRICE is treated as phantom (Rs.1, Rs.0.5, etc.)
# Anything above MAX_OPTION_PRICE is treated as a data error.
MIN_OPTION_PRICE = {
    "NIFTY": 5.0,
    "BANKNIFTY": 20.0,
    "FINNIFTY": 5.0,
    "MIDCPNIFTY": 5.0,
    "SENSEX": 10.0,
}
MAX_OPTION_PRICE = {
    "NIFTY": 3000.0,
    "BANKNIFTY": 15000.0,
    "FINNIFTY": 3000.0,
    "MIDCPNIFTY": 3000.0,
    "SENSEX": 10000.0,
}

# Cache for chain health (don't re-read JSON every call)
_CHAIN_HEALTH_CACHE = {}


def _read_chain(underlying):
    p = DCACHE / f"option_chain_{underlying}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def check_chain_health(underlying, use_cache=True):
    """FIX 2026-09-11: detect broken option chains.

    Detects:
      - PE prices inverted (decreasing strike should = decreasing PE price)
      - Spot value out of plausible range (e.g., NIFTY at 5,221)
      - Missing strikes (chain incomplete)
      - All-zero prices (chain is empty/stale)

    FIX 2026-09-16 12:50: added `unavailable` status for chains that the
    upstream data source (Kotak PROD scrip master) doesn't carry at all
    (e.g., FINNIFTY/MIDCPNIFTY/SENSEX in some sessions). The chain file
    exists but contains `{"error": "not_in_scrip_master"}`. This is NOT a
    broken chain — it's a known upstream gap. Treating it as broken would
    block trading for the whole session. `available=False, healthy=None`
    is the new shape; downstream consumers check availability before
    gating on health.

    Returns: {"healthy": bool, "available": bool, "issues": [str, ...], "spot": float}
    """
    if use_cache and underlying in _CHAIN_HEALTH_CACHE:
        return _CHAIN_HEALTH_CACHE[underlying]
    issues = []
    cd = _read_chain(underlying)
    if not cd:
        result = {"healthy": False, "available": False, "issues": ["chain file missing"], "spot": 0}
        _CHAIN_HEALTH_CACHE[underlying] = result
        return result
    # FIX 2026-09-16: chain file with explicit error → upstream gap, not broken data
    if "error" in cd:
        result = {
            "healthy": None,
            "available": False,
            "issues": [f"upstream_unavailable: {cd['error']}"],
            "spot": 0,
            "upstream_error": cd["error"],
        }
        _CHAIN_HEALTH_CACHE[underlying] = result
        return result
    spot = float(cd.get("spot", 0) or 0)
    strikes = cd.get("strikes", {}) or {}
    # Spot sanity
    spot_ranges = {
        "NIFTY": (15000, 35000),
        "BANKNIFTY": (35000, 80000),
        "FINNIFTY": (15000, 35000),
        "MIDCPNIFTY": (5000, 20000),
        "SENSEX": (50000, 100000),
    }
    lo, hi = spot_ranges.get(underlying, (0, 1000000))
    if not (lo <= spot <= hi):
        issues.append(f"spot {spot} out of plausible range [{lo}, {hi}]")
    # PE/CE price inversion check.
    # FIX 2026-09-16 13:00: the previous check was BACKWARDS for puts.
    # For puts: as strike goes UP, price should INCREASE (more intrinsic or
    # more time value as you move from deep-OTM to ATM/ITM). The old check
    # flagged this NORMAL behavior as inverted, so it would always fail on
    # any chain with multiple put strikes. The correct "broken" pattern
    # (yfinance Sep 11) was: as strike goes UP, price goes DOWN — the
    # OPPOSITE of the expected direction. Calls have the opposite expected
    # monotonicity: as strike goes UP, price should DECREASE.
    pe_strikes = []
    ce_strikes = []
    for k, v in strikes.items():
        if not isinstance(v, dict):
            continue
        s = v.get("strike", 0)
        p = v.get("price", 0)
        if not s or not p:
            continue
        if v.get("opt_type") == "PE":
            pe_strikes.append((s, p))
        elif v.get("opt_type") == "CE":
            ce_strikes.append((s, p))
    pe_strikes.sort()  # by strike ascending
    ce_strikes.sort()
    pe_inverted = 0
    for i in range(1, len(pe_strikes)):
        s0, p0 = pe_strikes[i - 1]
        s1, p1 = pe_strikes[i]
        # As strike goes UP, PE price should also go UP. Broken = price goes DOWN.
        if s1 > s0 and p1 < p0 * 0.95:
            pe_inverted += 1
    ce_inverted = 0
    for i in range(1, len(ce_strikes)):
        s0, p0 = ce_strikes[i - 1]
        s1, p1 = ce_strikes[i]
        # As strike goes UP, CE price should go DOWN. Broken = price goes UP.
        if s1 > s0 and p1 > p0 * 1.05:
            ce_inverted += 1
    total_inverted = pe_inverted + ce_inverted
    if total_inverted >= 3:
        issues.append(
            f"prices inverted on {total_inverted} strike pairs "
            f"(PE: {pe_inverted}, CE: {ce_inverted}; chain corrupted)"
        )
    # All-zero prices
    all_zero = all(
        v.get("price", 0) == 0
        for v in strikes.values()
        if isinstance(v, dict)
    )
    if all_zero and strikes:
        issues.append("all strikes have zero price (chain empty)")
    # Missing strikes near ATM
    if spot and strikes:
        atm = round(spot / 50) * 50 if underlying in ("NIFTY", "FINNIFTY") else round(spot / 100) * 100
        nearby = sum(1 for s in [atm, atm - 50, atm + 50, atm - 100, atm + 100]
                    if f"{s}_PE" in strikes or f"{s}_CE" in strikes)
        if nearby < 2:
            issues.append(f"only {nearby} strikes near ATM (chain incomplete)")
    result = {"healthy": len(issues) == 0, "available": True, "issues": issues, "spot": spot,
              "n_strikes": len(strikes), "n_inverted_pe_pairs": pe_inverted,
              "n_inverted_ce_pairs": ce_inverted}
    _CHAIN_HEALTH_CACHE[underlying] = result
    return result


def parse_symbol(symbol):
    """Parse NIFTY17SEP2623600PE -> {underlying, strike, opt_type, expiry}."""
    import re
    m = re.match(
        r'^(NIFTY|BANKNIFTY|FINNIFTY|MIDCPNIFTY|SENSEX)'
        r'(\d{2})([A-Z]{3})(\d{2})(\d+)(CE|PE)$',
        symbol.upper()
    )
    if not m:
        return None
    return {
        "underlying": m.group(1),
        "day": int(m.group(2)),
        "month": m.group(3),
        "year": int(m.group(4)),
        "strike": int(m.group(5)),
        "opt_type": m.group(6),
        "expiry_str": f"20{m.group(4)}-{_month_to_num(m.group(3)):02d}-{int(m.group(2)):02d}",
    }


def _month_to_num(m):
    months = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
              "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
    return months.get(m.upper(), 0)


def validate_fill_price(symbol, raw_price, expected_price=None):
    """FIX 2026-09-11: reject phantom fill prices."""
    parsed = parse_symbol(symbol)
    if not parsed:
        return {"ok": False, "reason": f"could not parse symbol {symbol!r}",
                "adjusted": None}
    underlying = parsed["underlying"]
    lo = MIN_OPTION_PRICE.get(underlying, 1.0)
    hi = MAX_OPTION_PRICE.get(underlying, 10000.0)
    if raw_price <= 0:
        return {"ok": False,
                "reason": f"price {raw_price} is zero/negative (phantom)",
                "adjusted": None}
    if raw_price < lo:
        return {"ok": False,
                "reason": f"price Rs.{raw_price:.2f} below sane minimum Rs.{lo} for {underlying} (likely phantom)",
                "adjusted": None}
    if raw_price > hi:
        return {"ok": False,
                "reason": f"price Rs.{raw_price:.2f} above sane maximum Rs.{hi} for {underlying} (likely data error)",
                "adjusted": None}
    if expected_price and expected_price > 0:
        ratio = raw_price / expected_price
        if ratio < 0.5 or ratio > 2.0:
            return {"ok": False,
                    "reason": f"chain price Rs.{raw_price:.2f} differs >2x from expected Rs.{expected_price:.2f} (chain may be wrong)",
                    "adjusted": None}
    return {"ok": True, "reason": "price OK", "adjusted": raw_price}


def bs_estimate(spot, strike, opt_type, days_to_expiry=5.0, iv=0.15, risk_free=0.065):
    """Black-Scholes option price (per share)."""
    if spot <= 0 or strike <= 0 or days_to_expiry <= 0 or iv <= 0:
        return None
    t = days_to_expiry / 365.0
    sigma_sqrt_t = iv * math.sqrt(t)
    d1 = (math.log(spot / strike) + (risk_free + 0.5 * iv * iv) * t) / sigma_sqrt_t
    d2 = d1 - sigma_sqrt_t

    def _cndf(x):
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
    if opt_type.upper() == "CE":
        price = spot * _cndf(d1) - strike * math.exp(-risk_free * t) * _cndf(d2)
    elif opt_type.upper() == "PE":
        price = strike * math.exp(-risk_free * t) * _cndf(-d2) - spot * _cndf(-d1)
    else:
        return None
    return round(max(price, 0.0), 2)


def get_safe_fill_price(symbol, raw_chain_price, expected_price=None, spot=None):
    """FIX 2026-09-11: the main fix for phantom fills."""
    parsed = parse_symbol(symbol)
    if not parsed:
        return {"price": 0, "source": "rejected",
                "reason": f"could not parse symbol {symbol!r}"}
    underlying = parsed["underlying"]
    strike = parsed["strike"]
    opt_type = parsed["opt_type"]
    # Compute days to expiry
    try:
        exp = datetime.strptime(parsed["expiry_str"], "%Y-%m-%d").date()
        days_to_exp = max(0, (exp - date.today()).days)
    except Exception:
        days_to_exp = 5
    # Try the chain price first
    if raw_chain_price and raw_chain_price > 0:
        v = validate_fill_price(symbol, raw_chain_price, expected_price)
        if v["ok"]:
            return {"price": raw_chain_price, "source": "chain", "reason": v["reason"]}
    # Fall back to Black-Scholes
    if spot and spot > 0:
        iv = 0.15
        try:
            cd = _read_chain(underlying)
            if cd:
                ivs = [v.get("iv") for v in cd.get("strikes", {}).values()
                       if isinstance(v, dict) and v.get("iv") and v.get("iv") > 0]
                if ivs:
                    iv = sum(ivs) / len(ivs)
        except Exception:
            pass
        bs_price = bs_estimate(spot, strike, opt_type, days_to_exp, iv=iv)
        if bs_price and bs_price > 0:
            v = validate_fill_price(symbol, bs_price, expected_price)
            if v["ok"]:
                return {"price": bs_price, "source": "bs", "reason": f"chain invalid, BS fallback (iv={iv:.2f})"}
    return {"price": 0, "source": "rejected",
            "reason": f"no valid price (chain={raw_chain_price}, expected={expected_price}, spot={spot})"}


def reset_cache():
    """Clear the chain health cache."""
    _CHAIN_HEALTH_CACHE.clear()
