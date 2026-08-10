"""UAT live test: connect to Kotak UAT, verify auth, subscribe to NIFTY/BANKNIFTY ticks,
fetch account state, report findings. No orders placed. Runs for ~60s to collect ticks.

Validates the full live path before we trust the bot with real UAT paper trading.
"""
import os
import sys
import time
from pathlib import Path

LOG = open("uat_live_test.log", "w", encoding="utf-8")
def o(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    LOG.write(line + "\n")
    LOG.flush()
    try:
        print(line)
    except UnicodeEncodeError:
        pass

sys.path.insert(0, '.')

# Suppress loguru stderr noise
import loguru
loguru.logger.remove()
loguru.logger.add("uat_live_test_logs.log", level="INFO")

# Load .env
from dotenv import load_dotenv
load_dotenv("config/credentials.env")

o("=" * 60)
o("KOTAK NEO UAT — LIVE TEST")
o("=" * 60)

# 1) Connect + auth
try:
    from neo_api_client import NeoAPI
    import pyotp

    api_key = os.getenv("KOTAK_API_KEY")
    mobile = os.getenv("KOTAK_MOBILE")
    ucc = os.getenv("KOTAK_UCC")
    mpin = os.getenv("KOTAK_MPIN")
    totp_secret = os.getenv("KOTAK_TOTP_SECRET")
    env = os.getenv("KOTAK_ENV", "uat")

    o(f"env={env}  ucc={ucc}  mobile={mobile}")

    client = NeoAPI(
        environment=env,
        access_token=api_key,
        consumer_key=api_key,
        neo_fin_key="neotradeapi",
    )
    o("NeoAPI init OK")

    totp = pyotp.TOTP(totp_secret).now()
    o(f"TOTP: {totp}")

    r1 = client.totp_login(mobile_number=mobile, ucc=ucc, totp=totp)
    if isinstance(r1, dict) and "error" in r1:
        o(f"TOTP login FAILED: {r1['error']}")
        sys.exit(1)
    o(f"TOTP login OK — got view token + sid")

    r2 = client.totp_validate(mpin=mpin)
    if isinstance(r2, dict) and "error" in r2:
        o(f"MPIN validate FAILED: {r2['error']}")
        sys.exit(1)
    o("MPIN validate OK — trading session active")

    # 2) Fetch account state
    o("\n--- Account state ---")
    try:
        margins = client.limits()
        o(f"Margins: {str(margins)[:500]}")
    except Exception as e:
        o(f"limits() error: {e}")
    try:
        positions = client.positions()
        o(f"Positions: {str(positions)[:500]}")
    except Exception as e:
        o(f"positions() error: {e}")
    try:
        holdings = client.holdings()
        o(f"Holdings: {str(holdings)[:300]}")
    except Exception as e:
        o(f"holdings() error: {e}")

    # 3) Fetch scrip master (NIFTY 50, BANKNIFTY index tokens)
    o("\n--- Scrip master search ---")
    try:
        nifty_search = client.scrip_search("NIFTY")
        o(f"NIFTY search result keys: {list(nifty_search.keys()) if isinstance(nifty_search, dict) else type(nifty_search)}")
        if isinstance(nifty_search, dict) and nifty_search.get("data"):
            data = nifty_search["data"]
            if isinstance(data, list) and data:
                o(f"  First match: {data[0]}")
    except Exception as e:
        o(f"scrip_search error: {e}")

    # 4) Subscribe to NIFTY + BANKNIFTY ticks
    o("\n--- WebSocket subscription ---")
    tick_count = {"nifty": 0, "banknifty": 0}
    last_ltp = {"nifty": 0, "banknifty": 0}

    def on_message(msg):
        try:
            if isinstance(msg, str):
                import json as _json
                msg = _json.loads(msg)
            if isinstance(msg, dict):
                # Kotak WS format
                ltp = msg.get("ltp") or msg.get("last_traded_price")
                tk = msg.get("tk") or msg.get("instrument_token") or ""
                if ltp and tk:
                    sym = "NIFTY" if "NIFTY" in str(tk).upper() or "26000" in str(tk) else ""
                    if "BANKNIFTY" in str(tk).upper() or "26009" in str(tk):
                        sym = "BANKNIFTY"
                    o(f"  TICK: token={tk} ltp={ltp}  ({sym})")
                    if "BANKNIFTY" in str(tk).upper():
                        tick_count["banknifty"] += 1
                        last_ltp["banknifty"] = ltp
                    else:
                        tick_count["nifty"] += 1
                        last_ltp["nifty"] = ltp
        except Exception as e:
            o(f"  msg parse: {e}")

    def on_error(e):
        o(f"  WS error: {e}")

    def on_close():
        o("  WS closed")

    def on_open():
        o("  WS opened")

    client.on_message = on_message
    client.on_error = on_error
    client.on_close = on_close
    client.on_open = on_open

    # Subscribe — tokens for NIFTY 50 (26000) and BANKNIFTY (26009) on nse_cm
    try:
        subscribe_tokens = [
            {"instrument_token": "26000", "exchange_segment": "nse_cm"},  # NIFTY 50 index
            {"instrument_token": "26009", "exchange_segment": "nse_cm"},  # BANKNIFTY index
        ]
        client.subscribe(instrument_tokens=subscribe_tokens, isIndex=True, isDepth=False)
        o(f"Subscribed: {subscribe_tokens}")
    except Exception as e:
        o(f"subscribe error: {e}")

    # Wait for ticks
    o("\n--- Listening for 30 seconds ---")
    time.sleep(30)

    o(f"\n--- Results ---")
    o(f"NIFTY ticks received: {tick_count['nifty']}  last_ltp: {last_ltp['nifty']}")
    o(f"BANKNIFTY ticks received: {tick_count['banknifty']}  last_ltp: {last_ltp['banknifty']}")
    if tick_count["nifty"] + tick_count["banknifty"] > 0:
        o("✅ LIVE TICK FEED WORKING — bot can trade against real UAT data")
    else:
        o("⚠ No ticks received — likely market closed OR WS not connected")
        o("  (market hours: 9:00 AM - 3:30 PM IST; this is " + time.strftime("%H:%M %Z") + ")")

    # 5) Logout
    try:
        client.logout()
        o("Logged out cleanly")
    except Exception as e:
        o(f"logout: {e}")

except Exception as e:
    o(f"FATAL: {type(e).__name__}: {e}")
    import traceback
    o(traceback.format_exc()[:2000])

o("\n" + "=" * 60)
o("UAT LIVE TEST COMPLETE")
o("=" * 60)
LOG.close()
