#!/usr/bin/env python
"""Quick test of KotakProdFeed — auth, scrip master, poll, verify ticks."""
import os
import sys
import time
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Load env
from dotenv import load_dotenv
load_dotenv(ROOT / "config" / "credentials.env")

from kotak_bot.data.kotak_prod_feed import KotakProdFeed

print("=== TEST: KotakProdFeed end-to-end ===\n")

feed = KotakProdFeed(
    env=os.environ.get('KOTAK_ENV', 'uat'),
    access_token=os.environ.get('KOTAK_API_KEY', ''),
    mobile=os.environ.get('KOTAK_MOBILE', ''),
    ucc=os.environ.get('KOTAK_UCC', ''),
    totp_secret=os.environ.get('KOTAK_TOTP_SECRET', ''),
    mpin=os.environ.get('KOTAK_MPIN', ''),
    poll_interval_sec=2.0,
)

ticks = []
def on_tick(t):
    ticks.append(t)
    print(f"  TICK: {t['symbol']:30s} ltp={t['ltp']:>10.2f} bid={t['bid']:>8.2f} ask={t['ask']:>8.2f} oi={t['oi']}")

feed.on_tick(on_tick)

print("Starting feed...")
feed.start()
time.sleep(2)

# Find BANKNIFTY weekly ATM
print("\nSubscribing to spot + sample strikes...")
import re
atm_bn = None
for ps, meta in feed._pSymbol_to_meta.items():
    if meta['sym'] == 'BANKNIFTY':
        atm_bn = meta['strike']
        break
print(f"First BANKNIFTY strike found: {atm_bn}")

# Subscribe to spot and a couple of options
to_sub = ['NIFTY', 'BANKNIFTY']
# Find a NIFTY 11AUG26 24500 CE strategy sym
nifty_atm_ce = None
for sym, ps in feed._strategySym_to_pSymbol.items():
    meta = feed._pSymbol_to_meta[ps]
    if meta['sym'] == 'NIFTY' and meta['opt'] == 'CE' and meta['strike'] == 24500:
        nifty_atm_ce = sym
        break
if nifty_atm_ce:
    to_sub.append(nifty_atm_ce)
    print(f"  NIFTY 24500 CE: {nifty_atm_ce}")

bn_atm_ce = None
for sym, ps in feed._strategySym_to_pSymbol.items():
    meta = feed._pSymbol_to_meta[ps]
    if meta['sym'] == 'BANKNIFTY' and meta['opt'] == 'CE' and meta['strike'] == 57400:
        bn_atm_ce = sym
        break
if bn_atm_ce:
    to_sub.append(bn_atm_ce)
    print(f"  BANKNIFTY 57400 CE: {bn_atm_ce}")

feed.subscribe(to_sub)
print(f"Subscribed to: {to_sub}")

print(f"\nPolling for 15s (interval {feed.poll_interval}s)...")
t0 = time.time()
while time.time() - t0 < 15:
    time.sleep(0.5)

print(f"\n=== RESULTS ===")
print(f"Total ticks received: {len(ticks)}")
for t in ticks[:20]:
    print(f"  {t['symbol']:30s} ltp={t['ltp']:>10.2f} bid={t['bid']:>8.2f} ask={t['ask']:>8.2f} oi={t['oi']}")
print(f"Latest in feed: {list(feed._latest.keys())[:5]}")
print(f"NIFTY ltp: {feed.get_ltp('NIFTY')}")
print(f"BANKNIFTY ltp: {feed.get_ltp('BANKNIFTY')}")
if nifty_atm_ce:
    print(f"{nifty_atm_ce} ltp: {feed.get_ltp(nifty_atm_ce)}")
    if feed._latest.get(nifty_atm_ce):
        print(f"  full: {feed._latest[nifty_atm_ce]}")

feed.stop()
print("Feed stopped. SUCCESS." if len(ticks) > 0 else "FEED FAILED — no ticks received")
