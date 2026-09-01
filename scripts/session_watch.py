"""session_watch.py — proactive Kotak session expiry watcher.

KotakProdFeed auto-reauths on next poll when session expires. But there's a
gap: between expiry and the next bot poll, the LLM may try to make a decision
based on stale data, OR the user may not realize auth is dead until 09:00 IST.

This module:
  1. Reads `data_cache/kotak_prod_session.json` periodically
  2. If expiring within 30 min: Telegram alert (one-time)
  3. If expired: Telegram alert + try re-auth via NeoClient (TOTP+MPIN unattended)
  4. Logs to `data_cache/session_watch.jsonl`

Wired into quant_service main loop (every 5 min).

Usage:
    from session_watch import check_session
    state = check_session()  # returns dict with status, remaining_sec, action
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'
SESSION_PATH = DATA / 'kotak_prod_session.json'
WATCH_LOG = DATA / 'session_watch.jsonl'
ALERTED_FILE = DATA / 'session_watch_alerted.json'

# Thresholds
WARN_BEFORE_SEC = 30 * 60     # 30 min
CRITICAL_BEFORE_SEC = 5 * 60  # 5 min


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_session() -> dict:
    if not SESSION_PATH.exists():
        return {}
    try:
        return json.loads(SESSION_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _load_alerted() -> dict:
    if not ALERTED_FILE.exists():
        return {}
    try:
        return json.loads(ALERTED_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save_alerted(alerted: dict) -> None:
    try:
        ALERTED_FILE.write_text(json.dumps(alerted, default=str), encoding='utf-8')
    except Exception:
        pass


def _send_telegram(msg: str, force: bool = False) -> bool:
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from telegram_alerter import _send
        return _send(msg, category="session", force=force)
    except Exception:
        return False


def _try_reauth() -> tuple[bool, str]:
    """Attempt unattended re-auth via TOTP+MPIN from env."""
    try:
        # Load credentials if not already
        env_path = ROOT / 'config' / 'credentials.env'
        if env_path.exists():
            for line in env_path.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                if k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
        sys.path.insert(0, str(ROOT))
        from kotak_bot.broker.neo_client import NeoClient
        nc = NeoClient()
        nc.connect()
        if hasattr(nc, '_save_session'):
            nc._save_session()
        if nc._client is not None and nc._connected:
            return True, f"reauth OK, env={os.environ.get('KOTAK_ENV', '?')}"
        return False, "connected but not _connected=True"
    except Exception as e:
        return False, f"reauth error: {str(e)[:200]}"


def check_session(force: bool = False) -> dict:
    """Check Kotak session. Alert on warning thresholds. Re-auth if expired.

    Args:
        force: if True, bypass throttling and force a re-auth attempt

    Returns: {status, remaining_sec, action, message}
    """
    sess = _read_session()
    now = time.time()
    expires_at = sess.get("expires_at")
    alerted = _load_alerted()
    alerted_key = "today"

    result = {
        "ts": _now_iso(),
        "session_present": bool(sess),
        "expires_at": expires_at,
        "remaining_sec": None,
        "status": "unknown",
        "action": "none",
        "message": "",
    }

    if not expires_at:
        result["status"] = "missing"
        result["message"] = "no kotek session file or no expires_at"
        # If no session, try to re-auth
        if force or (now - alerted.get(f"{alerted_key}_tried_reauth", 0) > 600):
            alerted[f"{alerted_key}_tried_reauth"] = now
            _save_alerted(alerted)
            ok, msg = _try_reauth()
            result["action"] = "tried_reauth"
            result["message"] = f"reauth: ok={ok}, {msg}"
            if ok:
                _send_telegram(f"🔄 Kotak session re-authed (was missing)\n{msg[:100]}", force=True)
        return result

    remaining = expires_at - now
    result["remaining_sec"] = int(remaining)

    if remaining < 0:
        result["status"] = "expired"
        result["message"] = f"session expired {-int(remaining/60)}m ago"
        # Try re-auth
        if force or (now - alerted.get(f"{alerted_key}_tried_reauth", 0) > 600):
            alerted[f"{alerted_key}_tried_reauth"] = now
            _save_alerted(alerted)
            ok, msg = _try_reauth()
            result["action"] = "tried_reauth"
            result["message"] += f" -> reauth: ok={ok}, {msg}"
            if ok:
                _send_telegram(f"🔄 Kotak session was expired, re-authed OK\n{msg[:100]}", force=True)
            else:
                _send_telegram(f"🚨 Kotak session EXPIRED + re-auth FAILED\n{result['message'][:200]}", force=True)
    elif remaining < CRITICAL_BEFORE_SEC:
        result["status"] = "critical"
        result["message"] = f"session expires in {int(remaining/60)}m"
        if not alerted.get(f"{alerted_key}_critical"):
            alerted[f"{alerted_key}_critical"] = now
            _save_alerted(alerted)
            _send_telegram(f"🚨 Kotak session CRITICAL: expires in {int(remaining/60)}m", force=True)
    elif remaining < WARN_BEFORE_SEC:
        result["status"] = "warning"
        result["message"] = f"session expires in {int(remaining/60)}m"
        if not alerted.get(f"{alerted_key}_warning"):
            alerted[f"{alerted_key}_warning"] = now
            _save_alerted(alerted)
            _send_telegram(f"⚠️ Kotak session expiring in {int(remaining/60)}m", force=False)
    else:
        result["status"] = "healthy"
        result["message"] = f"session valid for {int(remaining/3600)}h {int((remaining%3600)/60)}m"

    # Log
    try:
        with open(WATCH_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(result, default=str) + "\n")
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="Force re-auth attempt")
    args = p.parse_args()
    r = check_session(force=args.force)
    print(json.dumps(r, indent=2, default=str))
