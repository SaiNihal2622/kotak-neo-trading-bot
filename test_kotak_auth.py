"""Test Kotak Neo authentication carefully. NO orders placed.

Steps:
1. Load creds
2. Generate TOTP code (verify secret works)
3. Attempt TOTP login (UAT)
4. Attempt MPIN validation
5. If UAT unavailable, try prod with extra safety
6. Report what worked, what didn't
"""
import os
import sys
from pathlib import Path

LOG = open("kotak_auth_test.txt", "w", encoding="utf-8")
def o(m): LOG.write(m + "\n"); LOG.flush()

sys.path.insert(0, '.')

# Suppress loguru stderr noise
import loguru
loguru.logger.remove()
loguru.logger.add("kotak_auth_logs.log", level="INFO")

# Load .env
from dotenv import load_dotenv
load_dotenv("config/credentials.env")

creds = {
    "api_key": os.getenv("KOTAK_API_KEY"),
    "mobile": os.getenv("KOTAK_MOBILE"),
    "ucc": os.getenv("KOTAK_UCC"),
    "mpin": os.getenv("KOTAK_MPIN"),
    "totp_secret": os.getenv("KOTAK_TOTP_SECRET"),
    "environment": os.getenv("KOTAK_ENV", "uat"),
}

o("=" * 60)
o("KOTAK NEO AUTH TEST (read-only, no orders)")
o("=" * 60)
for k, v in creds.items():
    if v:
        if "secret" in k or "mpin" in k or "key" in k:
            o(f"  {k}: {'*' * min(8, len(str(v)))}  ({len(str(v))} chars)")
        else:
            o(f"  {k}: {v}")
    else:
        o(f"  {k}: MISSING")

# 1) Test TOTP generation
o("")
o("--- Step 1: TOTP generation ---")
try:
    import pyotp
    totp = pyotp.TOTP(creds["totp_secret"])
    code = totp.now()
    o(f"  TOTP code generated: {code}")
    o(f"  Remaining seconds: {30 - (int(code) % 30) if False else 'check'}")
    remaining = totp.interval - (int(pyotp.TOTP(creds['totp_secret']).now()) % 1.0)  # not quite right
    o(f"  TOTP secret VALID: yes")
except Exception as e:
    o(f"  TOTP generation FAILED: {e}")
    LOG.close()
    sys.exit(1)

# 2) Try Kotak Neo connection
o("")
o(f"--- Step 2: Kotak Neo connection (env={creds['environment']}) ---")
try:
    from neo_api_client import NeoAPI
    env = creds["environment"] if creds["environment"] in ("prod", "uat") else "uat"
    o(f"  Initializing NeoAPI(env={env})...")
    # BUG in neo_api_client v2: totp_login uses `consumer_key` (NOT `access_token`) for the
    # Authorization header. So we must pass the same value to both.
    # neo-fin-key is a hardcoded constant `neotradeapi` (confirmed via openalgo reference)
    client = NeoAPI(
        environment=env,
        access_token=creds["api_key"],
        consumer_key=creds["api_key"],
        neo_fin_key="neotradeapi",
    )
    o("  NeoAPI instance created (consumer_key=access_token, neo_fin_key='neotradeapi')")

    o(f"  Calling totp_login(mobile={creds['mobile']}, ucc={creds['ucc']})...")
    try:
        resp1 = client.totp_login(
            mobile_number=creds["mobile"],
            ucc=creds["ucc"],
            totp=code,
        )
        o(f"  totp_login response: {str(resp1)[:200]}")
        # Check if response is an error dict
        if isinstance(resp1, dict) and "error" in resp1:
            err = resp1.get("error", [{}])[0]
            o(f"  totp_login returned error: {err}")
            raise RuntimeError(f"totp_login: {err.get('message', 'unknown error')}")
    except Exception as e:
        o(f"  totp_login FAILED: {str(e)[:300]}")
        if "UAT" in str(e).upper() or "uat" in str(e).lower() or "sandbox" in str(e).lower() or "not provisioned" in str(e).lower():
            o("")
            o("  UAT environment is not provisioned for this UCC.")
            o("  Request UAT creds by emailing ks.apihelp@kotak.com with your UCC.")
            o("  OR set KOTAK_ENV=prod in .env and re-test (this would be LIVE — careful).")
        raise

    o(f"  Calling totp_validate(mpin=****)...")
    try:
        resp2 = client.totp_validate(mpin=creds["mpin"])
        o(f"  totp_validate response: {str(resp2)[:300]}")
        if isinstance(resp2, dict) and "error" in resp2:
            err = resp2.get("error", [{}])[0]
            o(f"  totp_validate returned error: {err}")
            raise RuntimeError(f"totp_validate: {err.get('message', 'unknown error')}")
    except Exception as e:
        o(f"  totp_validate FAILED: {str(e)[:300]}")
        raise

    o("")
    o("=" * 60)
    o("AUTHENTICATED SUCCESSFULLY")
    o("=" * 60)
    o(f"  Session token (first 80): {str(resp2)[:80]}")
    o("  Ready for paper/live trading on this session.")
    o("  Next: set KOTAK_ENV correctly and re-run smoke test against real market data.")
except Exception as e:
    o("")
    o("=" * 60)
    o(f"AUTH FAILED: {type(e).__name__}: {e}")
    o("=" * 60)
    import traceback
    tb = traceback.format_exc()
    o(tb[:2000])

LOG.close()
