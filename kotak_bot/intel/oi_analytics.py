"""OI / GEX / max-pain analytics for option chain.

Inputs: {symbol: Tick} dict from LiveFeed.get_oi_map().
Outputs: aggregated by strike.

Functions:
- oi_walls(symbol_tick_map) -> {resistance, support, ...}
- max_pain(symbol_tick_map) -> strike
- pcr(symbol_tick_map) -> float
- gex(spot, symbol_tick_map, contract_multiplier) -> dict
- oi_aware_strike_selection(spot, symbol_tick_map, regime) -> dict
"""
from __future__ import annotations

import math
from typing import Optional

from loguru import logger


def _aggregate_by_strike(symbol_tick_map: dict) -> dict:
    """Convert {symbol: Tick} to {strike: {ce_oi, pe_oi, ce_ltp, pe_ltp}}."""
    out = {}
    for sym, t in symbol_tick_map.items():
        if not hasattr(t, "oi") and not hasattr(t, "ltp"):
            continue
        if not (sym.endswith("CE") or sym.endswith("PE")):
            continue
        opt_type = sym[-2:]
        rest = sym[:-2]
        # symbol like NIFTY10AUG2625000CE — strip 7-char expiry then take strike
        if len(rest) < 8:
            continue
        try:
            strike = int(rest[7:])
        except (ValueError, IndexError):
            continue
        if strike not in out:
            out[strike] = {"ce_oi": 0, "pe_oi": 0, "ce_ltp": 0.0, "pe_ltp": 0.0}
        if opt_type == "CE":
            out[strike]["ce_oi"] = getattr(t, "oi", 0) or 0
            out[strike]["ce_ltp"] = getattr(t, "ltp", 0.0) or 0.0
        else:
            out[strike]["pe_oi"] = getattr(t, "oi", 0) or 0
            out[strike]["pe_ltp"] = getattr(t, "ltp", 0.0) or 0.0
    return out


def oi_walls(symbol_tick_map: dict) -> dict:
    """Find max call OI (resistance) and max put OI (support) strikes."""
    agg = _aggregate_by_strike(symbol_tick_map)
    if not agg:
        return {"resistance": None, "support": None}
    max_call = max(agg.items(), key=lambda kv: kv[1].get("ce_oi", 0))
    max_put = max(agg.items(), key=lambda kv: kv[1].get("pe_oi", 0))
    return {
        "resistance": max_call[0] if max_call[1].get("ce_oi", 0) > 0 else None,
        "support": max_put[0] if max_put[1].get("pe_oi", 0) > 0 else None,
        "resistance_oi": max_call[1].get("ce_oi", 0),
        "support_oi": max_put[1].get("pe_oi", 0),
    }


def max_pain(symbol_tick_map: dict) -> Optional[int]:
    """Find strike with max total OI (max option seller pain at expiry)."""
    agg = _aggregate_by_strike(symbol_tick_map)
    if not agg:
        return None
    total_oi = {s: d.get("ce_oi", 0) + d.get("pe_oi", 0) for s, d in agg.items()}
    if not total_oi:
        return None
    return max(total_oi.items(), key=lambda kv: kv[1])[0]


def pcr(symbol_tick_map: dict) -> float:
    """Put-Call Ratio by OI. >1.0 = bullish, <0.7 = bearish."""
    agg = _aggregate_by_strike(symbol_tick_map)
    total_ce = sum(d.get("ce_oi", 0) for d in agg.values())
    total_pe = sum(d.get("pe_oi", 0) for d in agg.values())
    if total_ce == 0:
        return 0.0
    return total_pe / total_ce


def gex(spot: float, symbol_tick_map: dict, contract_multiplier: int = 1) -> dict:
    """Gamma Exposure (GEX) — measures market maker gamma positioning."""
    if not symbol_tick_map or spot <= 0:
        return {"net_gex": 0, "by_strike": {}, "regime": "neutral"}
    agg = _aggregate_by_strike(symbol_tick_map)
    by_strike = {}
    net = 0.0
    for strike, d in agg.items():
        distance = abs(spot - strike) / spot
        gamma_proxy = max(0.0, 0.04 * math.exp(-distance * 8))
        ce_gamma = gamma_proxy * d.get("ce_oi", 0) * contract_multiplier
        pe_gamma = gamma_proxy * d.get("pe_oi", 0) * contract_multiplier
        # short positions have negative gamma (option sellers = market makers)
        gex_at_strike = -(ce_gamma + pe_gamma)
        by_strike[strike] = gex_at_strike
        net += gex_at_strike
    if net > 0:
        regime = "long_gamma"
    elif net < -1000:
        regime = "short_gamma"
    else:
        regime = "neutral"
    return {"net_gex": net, "by_strike": by_strike, "regime": regime}


def oi_aware_strike_selection(spot: float, symbol_tick_map: dict, regime: str = "range",
                              step: int = 50, preferred_wing: int = 100) -> dict:
    """Use OI walls to pick iron condor short strikes that align with key levels."""
    walls = oi_walls(symbol_tick_map)
    resistance = walls.get("resistance")
    support = walls.get("support")
    mp = max_pain(symbol_tick_map) or int(round(spot / step) * step)
    if resistance is None or support is None:
        atm = int(round(spot / step) * step)
        return {
            "short_ce": atm + preferred_wing,
            "short_pe": atm - preferred_wing,
            "long_ce": atm + preferred_wing * 2,
            "long_pe": atm - preferred_wing * 2,
            "reason": f"default wings (no OI walls), atm={atm}, max_pain={mp}",
        }
    short_ce = max(resistance, int(round(spot / step) * step) + preferred_wing)
    short_pe = min(support, int(round(spot / step) * step) - preferred_wing)
    short_ce = int(round(short_ce / step) * step)
    short_pe = int(round(short_pe / step) * step)
    long_ce = short_ce + preferred_wing
    long_pe = short_pe - preferred_wing
    return {
        "short_ce": short_ce,
        "short_pe": short_pe,
        "long_ce": long_ce,
        "long_pe": long_pe,
        "reason": f"OI-aware: resistance={resistance}, support={support}, max_pain={mp}",
    }
