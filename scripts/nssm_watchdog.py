"""nssm_watchdog.py - 3rd-layer watchdog for 24/7 NSSM health.

FIX 2026-09-07 01:20: adds a third watchdog layer that runs every 15 min via
Windows Task Scheduler (schtasks). The 3 existing layers:
  1. Bot's self-heal (every 5 min in main loop) - 7 recipes
  2. Brain's bot watchdog (every 5 min in watch_loop) - 1 recipe
  3. Daily tasks (3x/day: 08:25, 15:30, 23:00) - 12 checks
...all have a coverage gap: if both NSSM services die simultaneously,
no recovery until the next daily task fires (8.5h gap max).

This script fills the gap with a 4th layer that runs every 15 min.
  - Checks KotakBotPaper NSSM state. If STOPPED, calls nssm start.
  - Checks KotakQuantService NSSM state. If STOPPED, calls nssm start.
  - Sends Telegram alert on every restart (with cooldown).
  - Logs to Logs/nssm_watchdog.log.

Runtimes: typically <5 sec. Safe to run every 15 min. Cost: negligible.

Install via:
  schtasks /create /tn kotakak-nssm-watchdog /tr "python C:\\\\path\\\\nssm_watchdog.py" /sc minute /mo 15 /ru SYSTEM /rl HIGHEST /f
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.resolve()
LOG = ROOT / "Logs" / "nssm_watchdog.log"
STATE = ROOT / "data_cache" / "nssm_watchdog_state.json"
COOLDOWN_SEC = 1800  # 30 min between Telegram alerts for the same service

SERVICES = ["KotakBotPaper", "KotakQuantService"]
NSSM = r"C:\Tools\nssm\nssm-2.24\win64\nssm.exe"


def _log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now().isoformat()}] {msg}"
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _send_telegram(text: str) -> bool:
    """Try to send a Telegram message. Fails silently if creds are missing."""
    try:
        # Load creds (SYSTEM context has no env vars)
        cred_path = ROOT / "config" / "credentials.env"
        if cred_path.exists():
            for line in cred_path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
        sys.path.insert(0, str(ROOT))
        from scripts._telegram_alert import send_telegram
        return send_telegram(text)
    except Exception as e:
        _log(f"  telegram failed: {e}")
        return False


def _load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_alert_ts": {}}


def _save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    try:
        STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


def _check_and_start(service: str, state: dict) -> dict:
    """Check if NSSM service is STOPPED. If so, start it. Returns result."""
    result = {"service": service, "state_before": "unknown", "started": False, "msg": ""}
    try:
        sc = subprocess.run(
            ["sc", "query", service],
            capture_output=True, text=True, timeout=10,
        )
        out = sc.stdout or ""
        result["state_before"] = "STOPPED" if "STOPPED" in out.upper() and "1  STOPPED" in out.upper() else "RUNNING"
    except Exception as e:
        result["msg"] = f"sc query failed: {e}"
        return result
    if result["state_before"] != "STOPPED":
        result["msg"] = "ok"
        return result
    # Service is STOPPED. Try to start it.
    _log(f"[WARN] {service} NSSM is STOPPED. Starting via nssm.")
    try:
        ns = subprocess.run(
            [NSSM, "start", service],
            capture_output=True, text=True, timeout=20,
        )
        result["started"] = ns.returncode in (0, 1)  # 0=ok, 1=START_PENDING
        result["msg"] = f"nssm start exit={ns.returncode} out={(ns.stdout or ns.stderr or '').strip()[:200]}"
    except Exception as e:
        result["msg"] = f"nssm start failed: {e}"
    # Alert with cooldown
    if result["started"]:
        last_alert = state.get("last_alert_ts", {}).get(service, 0)
        if time.time() - last_alert > COOLDOWN_SEC:
            _send_telegram(
                f"♻️ [NSSM-WATCHDOG] {service} was STOPPED. "
                f"Started via nssm. exit={ns.returncode}. "
                f"This is a 3rd-layer watchdog (every 15 min) catching what "
                f"the bot/brain watchdogs missed."
            )
            state.setdefault("last_alert_ts", {})[service] = time.time()
    return result


def main() -> int:
    _log(f"=== nssm_watchdog run at {datetime.now().isoformat()} ===")
    state = _load_state()
    all_ok = True
    for svc in SERVICES:
        result = _check_and_start(svc, state)
        _log(f"  {svc}: state={result['state_before']} started={result['started']} msg={result['msg'][:120]}")
        if result["state_before"] != "RUNNING" and not result["started"]:
            all_ok = False
    _save_state(state)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
