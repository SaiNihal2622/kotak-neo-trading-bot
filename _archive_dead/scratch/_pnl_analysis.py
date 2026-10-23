"""Calculate the actual vs intended iron condor P&L."""
import json

with open('data_cache/paper_state.json', 'r', encoding='utf-8') as f:
    s = json.load(f)

print("=" * 70)
print("ACTUAL POSITIONS (today)")
print("=" * 70)
total_cost = 0
total_value = 0
for sym, pos in s['positions'].items():
    qty = pos['qty']
    avg = pos['avg_price']
    ltp = pos['ltp']
    cost = qty * avg
    value = qty * ltp
    pnl = value - cost
    pnl_pct = (ltp - avg) / avg * 100
    print(f"  {sym}:")
    print(f"    qty={qty}, avg=Rs.{avg:.2f}, ltp=Rs.{ltp:.2f}")
    print(f"    cost=Rs.{cost:,.0f}, value=Rs.{value:,.0f}, pnl=Rs.{pnl:+,.0f} ({pnl_pct:+.1f}%)")
    total_cost += cost
    total_value += value

total_pnl = total_value - total_cost
print()
print(f"TOTAL COST: Rs.{total_cost:,.0f}")
print(f"TOTAL VALUE: Rs.{total_value:,.0f}")
print(f"TOTAL UNREALIZED P&L: Rs.{total_pnl:+,.0f}")

print()
print("=" * 70)
print("WHAT AN IRON condOR WOULD HAVE LOOKED")
print("=" * 70)
print()
print("Intended structure (iron condor_nifty):")
print("  SELL 22950 CE @ ~2.50 (collect)")
print("  BUY  23050 CE @ ~1.50 (wing)")
print("  SELL 22550 PE @ ~12.00 (collect)")
print("  BUY  22450 PE @ ~8.50 (wing)")
print()
print("Per 75 qty (1 lot):")
print("  Sell CE credit: Rs.2.50 × 75 = Rs.187.5")
print("  Buy  CE debit:  Rs.1.50 × 75 = Rs.112.5")
print("  Sell PE credit: Rs.12.0 × 75 = Rs.900")
print("  Buy  PE debit:  Rs.8.50 × 75 = Rs.637.5")
print()
print(f"  Net credit per lot: Rs.{(2.50-1.50+12.0-8.50)*75:,.0f}")
print(f"  Max loss per lot: Rs.{(100-(2.50-1.50+12.0-8.50))*75:,.0f} (wing width 100)")
print()
print("Across 18 lots (1350 qty):")
print(f"  Max gain (full premium kept): Rs.{(2.50-1.50+12.0-8.50)*75*18:,.0f}")
print(f"  Max loss (one side breached): Rs.{(100-(2.50-1.50+12.0-8.50))*75*18:,.0f}")
print()
print("=" * 70)
print("P&L DELTA (actual vs intended)")
print("=" * 70)
print(f"  Actual:           Rs.{total_pnl:+,.0f}")
print(f"  Intended (gain):  +Rs.{(2.50-1.50+12.0-8.50)*75*18:,.0f}")
print(f"  Delta (missed):   Rs.{total_pnl*-1 + (2.50-1.50+12.0-8.50)*75*18:,.0f} swing")
print()
print("=" * 70)
print("ROOT CAUSE")
print("=" * 70)
print()
print("50 BUY orders executed (all got filled).")
print("ZERO SELL orders executed (all rejected after 60s).")
print()
print("SELL legs failed because PaperClient has 0 live ticks.")
print("Without ticks, the auto-snap can't fire.")
print("LLM proposes limit=113 while current bid=12 → 60s timeout → reject.")
print()
print("Net effect: bot THINKS it has iron condor but actually has LONG STRANGLE.")
print("Long strangle = unlimited downside, premium decay every day.")