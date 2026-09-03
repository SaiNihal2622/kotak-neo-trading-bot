"""Quick MTM calculator with Black-Scholes fallback for strikes not in chain.

FIX 2026-09-03 14:30: live option LTPs were not visible to the agent.
- Primary source: option_chains.json (live Kotak option prices, updated every 5 min)
- Fallback: Black-Scholes from spot + IV estimated from ATM IV
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
chains = json.loads((ROOT / "data_cache" / "option_chains.json").read_text(encoding="utf-8"))
ps = json.loads((ROOT / "data_cache" / "paper_state.json").read_text(encoding="utf-8"))


def bs_price(spot: float, strike: float, t_years: float, vol: float, rate: float = 0.06, opt_type: str = "CE") -> float:
    """Black-Scholes option price. spot/strike in INR, vol annualized, t_years in years."""
    if t_years <= 0 or vol <= 0 or spot <= 0 or strike <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * t_years) / (vol * math.sqrt(t_years))
    d2 = d1 - vol * math.sqrt(t_years)

    def cdf(x):
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    if opt_type == "CE":
        return spot * cdf(d1) - strike * math.exp(-rate * t_years) * cdf(d2)
    else:
        return strike * math.exp(-rate * t_years) * cdf(-d2) - spot * cdf(-d1)


def get_live_or_estimate(sym: str, und: str, strike: int, opt: str, chain: dict) -> tuple:
    """Returns (ltp, source) where source is 'chain' or 'bs_estimate'."""
    strike_key = f"{strike}_{opt}"
    strikes = chain.get("strikes", {})
    if strike_key in strikes:
        return strikes[strike_key].get("price", 0), "chain"
    # Try matching by strike + opt
    for k, v in strikes.items():
        if v.get("strike") == strike and v.get("opt_type") == opt:
            return v.get("price", 0), "chain"
    # Black-Scholes fallback using ATM IV
    spot = chain.get("spot", 0)
    atm_iv = None
    atm_strike = chain.get("atm_strike", strike)
    # Find nearest strike IV
    for k, v in strikes.items():
        if abs(v.get("strike", 0) - atm_strike) < 50:
            atm_iv = v.get("iv", 0.16)
            break
    if atm_iv is None:
        atm_iv = 0.16
    # Time to expiry: 0.02 years (intraday, ~1 hour to 15:30 close = 0.006 yr, use 0.02 to be conservative)
    t_years = 0.02
    est = bs_price(spot, strike, t_years, atm_iv, opt_type=opt)
    return est, f"BS(iv={atm_iv:.3f}, t={t_years})"


positions = ps.get("positions", {})

print("Symbol                                  Qty   Entry   LiveLTP          MTM/leg      Source")
print("-" * 110)
total_mtm = 0.0
for sym, p in positions.items():
    qty = p.get("qty", 0)
    avg = p.get("avg_price", 0)
    und = p.get("underlying", "")
    strike = int(p.get("strike", 0))
    opt = p.get("option_type", "")
    chain = chains.get("chains", {}).get(und, {})
    ltp, source = get_live_or_estimate(sym, und, strike, opt, chain)
    mtm = (ltp - avg) * qty
    total_mtm += mtm
    ltp_str = f"{ltp:8.2f}" if ltp else "    n/a"
    mtm_str = f"{mtm:+10.2f}" if ltp else "      n/a"
    print(f"{sym:38} {qty:+5d}  {avg:7.2f}  {ltp_str}  {mtm_str:>10}   {source}")
print("-" * 110)
print(f"{'TOTAL MTM':>88}  {total_mtm:+10.2f}")
cash = ps.get("cash", 0)
print(f"{'Cash':>88}  {cash:10.2f}")
print(f"{'Total portfolio value (cash + MTM)':>88}  {cash + total_mtm:10.2f}")
