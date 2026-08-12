"""Smoke test for NeoClient READ path against PROD.

Tests everything except place_order. Verifies that the live broker
infrastructure (auth, positions, margins, order report) actually works
against Kotak PROD before we risk real money.

This test should pass BEFORE flipping mode: live. If it fails, do NOT
go live — there's a real money risk.
"""
import os
import sys
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / "config" / "credentials.env")

# SAFETY: refuse to run unless explicitly confirmed
if os.environ.get("NEO_SMOKE_CONFIRM") != "YES":
    print("=" * 60)
    print("NEO CLIENT SMOKE TEST (READ path only — no orders placed)")
    print("=" * 60)
    print()
    print("This test connects to PROD and reads:")
    print("  - get_positions (your open positions)")
    print("  - get_margins (your account balance)")
    print("  - get_limits (margin limits)")
    print("  - get_order_report (today's orders)")
    print("  - get_trade_report (today's fills)")
    print()
    print("It does NOT place any orders. Safe to run anytime.")
    print()
    print("Re-run with NEO_SMOKE_CONFIRM=YES to proceed.")
    print()
    sys.exit(0)

print("=" * 60)
print("NEO CLIENT SMOKE TEST — connecting to PROD")
print("=" * 60)
print()

from kotak_bot.broker.neo_client import NeoClient

# Capture timing for the heartbeat
client = NeoClient()
print(f"[{datetime.now().isoformat()}] Connecting...")
t0 = datetime.now()
client.connect()
print(f"[{(datetime.now()-t0).total_seconds():.2f}s] Connected to PROD")
print(f"  baseUrl: {client._base_url}")
print(f"  algo_id: {client._algo_id}")
print()

# 1) get_positions
print("--- 1) get_positions() ---")
try:
    positions = client.get_positions()
    print(f"  Returned {len(positions)} open positions")
    for p in positions[:5]:
        print(f"    {p.symbol:30s}  qty={p.qty:+d}  avg={p.avg_price:.2f}  pnl=Rs.{p.pnl:.0f}")
    if len(positions) > 5:
        print(f"    ... and {len(positions)-5} more")
except Exception as e:
    print(f"  ERR: {e}")
print()

# 2) get_margins
print("--- 2) get_margins() ---")
try:
    margins = client.get_margins()
    print(f"  Available: Rs.{margins.get('available', 0):,.0f}")
    print(f"  Used:      Rs.{margins.get('used', 0):,.0f}")
    print(f"  Total:     Rs.{margins.get('total', 0):,.0f}")
except Exception as e:
    print(f"  ERR: {e}")
print()

# 3) get_segment_limits
print("--- 3) get_segment_limits(FO, NSE, ALL) ---")
try:
    limits = client.get_segment_limits(segment="FO", exchange="NSE", product="ALL")
    if isinstance(limits, dict):
        # show a few key fields
        keys = list(limits.keys())[:8]
        for k in keys:
            v = limits[k]
            if isinstance(v, (int, float, str)):
                print(f"  {k}: {v}")
            else:
                print(f"  {k}: ({type(v).__name__})")
    else:
        print(f"  Returned: {str(limits)[:200]}")
except Exception as e:
    print(f"  ERR: {e}")
print()

# 4) get_order_report (today's orders)
print("--- 4) get_order_report() ---")
try:
    orders = client.get_order_report()
    print(f"  Today: {len(orders) if isinstance(orders, list) else 'N/A'} orders")
    if isinstance(orders, list):
        for o in orders[:5]:
            sym = o.get("trdSym", "?")
            qty = o.get("qty", 0)
            price = o.get("prc", "0")
            status = o.get("ordSt", "?")
            print(f"    {sym:30s}  qty={qty}  price={price}  status={status}")
except Exception as e:
    print(f"  ERR: {e}")
print()

# 5) get_trade_report
print("--- 5) get_trade_report() ---")
try:
    trades = client.get_trade_report()
    print(f"  Today: {len(trades) if isinstance(trades, list) else 'N/A'} fills")
except Exception as e:
    print(f"  ERR: {e}")
print()

# 6) Heartbeat
print("--- 6) heartbeat ---")
print(f"  Last heartbeat: {client.heartbeat()}")
print()

# 7) Load scrip master
print("--- 7) load_scrip_master(['nse_fo']) ---")
try:
    t0 = datetime.now()
    count = client.load_scrip_master(["nse_fo"])
    dt = (datetime.now() - t0).total_seconds()
    print(f"  Loaded {count} NIFTY/BANKNIFTY contracts in {dt:.1f}s")
    print(f"  Tokens indexed: {len(client._token_index)}")
except Exception as e:
    print(f"  ERR: {e}")
print()

print("=" * 60)
print("SMOKE TEST COMPLETE")
print("=" * 60)
print()
print("If you saw real numbers above, the READ path works on PROD.")
print("This means:")
print("  - Auth is working (TOTP + MPIN flow OK)")
print("  - PROD baseUrl reachable")
print("  - Orders/positions/margins can be read")
print()
print("Still to verify before live trading:")
print("  - place_order (real order placement) — DO THIS AT 9:30 IST, NOT NOW")
print("  - bracket order SL/target leg execution")
print("  - get_quote for option chain")
print("  - cancel_order / modify_order")
print()
print("Recommended: run /scripts/e2e_paper_test.py daily at 8:55 IST")
print("            run this script weekly to verify PROD auth still works")
print()
print("Disconnecting...")
client.disconnect()
print("Done.")
