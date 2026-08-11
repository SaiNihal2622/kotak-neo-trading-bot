#!/usr/bin/env python
"""Integration test: LiveFeed(mode='live_kotak') with PaperClient."""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / "config" / "credentials.env")

from kotak_bot.data.live_feed import LiveFeed
from kotak_bot.broker.paper_client import PaperClient

print("=== INTEGRATION TEST: LiveFeed(live_kotak) + PaperClient ===\n")

# Build a minimal paper client (just to satisfy the constructor)
paper = PaperClient(starting_capital=100000.0, persist_path="data_cache/test_paper_state.json")

# Build the live feed
feed = LiveFeed(mode="live_kotak", broker=paper)

ticks = []
def on_tick(t):
    ticks.append(t)

feed.on_tick(on_tick)
feed.start()
print("Feed started. Waiting 5s for initial auth + scrip master...")
time.sleep(5)

# Subscribe to a few NIFTY + BANKNIFTY options
print("\nSubscribing to spot + sample strikes...")
to_sub = ['NIFTY', 'BANKNIFTY']
nifty_atm_ce = None
for sym, ps in feed._kotak_feed._strategySym_to_pSymbol.items():
    meta = feed._kotak_feed._pSymbol_to_meta[ps]
    if meta['sym'] == 'NIFTY' and meta['opt'] == 'CE' and meta['strike'] == 24500:
        nifty_atm_ce = sym
        break
if nifty_atm_ce:
    to_sub.append(nifty_atm_ce)
    print(f"  NIFTY 24500 CE: {nifty_atm_ce}")

bn_atm_ce = None
for sym, ps in feed._kotak_feed._strategySym_to_pSymbol.items():
    meta = feed._kotak_feed._pSymbol_to_meta[ps]
    if meta['sym'] == 'BANKNIFTY' and meta['opt'] == 'CE' and meta['strike'] == 57400:
        bn_atm_ce = sym
        break
if bn_atm_ce:
    to_sub.append(bn_atm_ce)
    print(f"  BANKNIFTY 57400 CE: {bn_atm_ce}")

feed.subscribe(to_sub)

print(f"\nPolling 10s...")
t0 = time.time()
while time.time() - t0 < 10:
    time.sleep(0.5)

print(f"\n=== RESULTS ===")
print(f"Ticks via LiveFeed.on_tick callback: {len(ticks)}")
print(f"Latest in feed: {len(feed._latest)} unique symbols")
for sym in list(feed._latest.keys())[:10]:
    t = feed._latest[sym]
    print(f"  {sym:30s} ltp={t.ltp:>10.2f} bid={t.bid:>8.2f} ask={t.ask:>8.2f} oi={t.oi}")

# Test get_ltp
print(f"\nget_ltp('NIFTY') = {feed.get_ltp('NIFTY')}")
print(f"get_ltp('BANKNIFTY') = {feed.get_ltp('BANKNIFTY')}")
if nifty_atm_ce:
    print(f"get_ltp('{nifty_atm_ce}') = {feed.get_ltp(nifty_atm_ce)}")

# Test get_momentum
print(f"get_momentum('NIFTY', 5) = {feed.get_momentum('NIFTY', 5):.4f}")

# Test get_oi_map
oi_map = feed.get_oi_map('NIFTY')
print(f"get_oi_map('NIFTY'): {len(oi_map)} strikes")

feed.stop()
print("\n=== TEST PASSED ===" if len(ticks) > 5 else "=== TEST FAILED — too few ticks ===")
