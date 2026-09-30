"""247 watchdog — checks per-service heartbeats and restarts dead/stuck services.

PHASE 6 FIX 2026-09-30: makes the system 24/7 by automatically restarting any
of the 4 subsystems that goes stale (no heartbeat for >90s). Runs as a
single check cycle when invoked, or loops forever with --loop.

This is the "non-glued" reliability layer. Combined with NSSM-managed
services (auto-restart on process exit), the system now self-heals:
- Process crash → NSSM restarts (fast, ~5s)
- Process stuck (deadlock, infinite loop) → watchdog restarts via NSSM
- Heartbeat writer itself dead → watchdog itself is restarted by the
  kotak-bot-watchdog cron (every 5 min) via Start-Process fallback

Usage:
    .venv\Scripts\python.exe scripts\watchdog_247.py            # one cycle
    .venv\Scripts\python.exe scripts\watchdog_247.py --loop 30  # loop every 30s
    .venv\Scripts\python.exe scripts\watchdog_247.py --quiet     # no Telegram on ok

Outputs JSON to stdout for easy cron piping; also writes
data_cache/watchdog_log.jsonl (append-only) for post-mortem.
Sends Telegram only on restart events (silent on OK).

The Telegram notification is OPT-IN — set KOTAK_WATCHDOG_TG=1 in env to enable.
The 247_watchdog cron can be configured to call this script.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
IST = timezone(timedelta(hours=5, minutes=30))


SERVICE_CONFIGS = [
    ("core_api",      "KotakCoreAPI",      "system.core.api.server"),
    ("brain_bridge",  "KotakBrainBridge",  "system.bridge.brain_bridge"),
    ("brain_daemon",  "KotakBrainDaemon",  "system.brain.brain_daemon"),
    ("exec_gateway",  "KotakExecGateway",  "system.exec.exec_gateway"),
]


def now_ist() -> str:
    return datetime.now(IST).isoformat()


def log_event(record: dict) -> None:
    """Append to data_cache/watchdog_log.jsonl."""
    log_path = PROJECT_ROOT / "data_cache" / "watchdog_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": now_ist(), **record}
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        print(f"watchdog log write failed: {e}", file=sys.stderr)


def send_telegram(text: str) -> bool:
    """Send a Telegram message if KOTAK_WATCHDOG_TG=1 is set.
    Token + chat_id are read from config/credentials.env.
    """
    if os.environ.get("KOTAK_WATCHDOG_TG", "") != "1":
        return False
    try:
        cred_path = PROJECT_ROOT / "config" / "credentials.env"
        if not cred_path.exists():
            return False
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen

        env_lines = cred_path.read_text(encoding="utf-8-sig").splitlines()
        env = {}
        for line in env_lines:
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")

        token = env.get("TELEGRAM_BOT_TOKEN", "")
        chat = env.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat:
            return False
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urlencode({"chat_id": chat, "text": text[:3500]}).encode("utf-8")
        req = Request(url, data=data, method="POST")
        with urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception as e:
        print(f"telegram send failed: {e}", file=sys.stderr)
        return False


def run_once(quiet: bool = False) -> list[dict]:
    """Run one watchdog check cycle. Returns list of action records."""
    from system.common.heartbeat import HeartbeatWatchdog
    wd = HeartbeatWatchdog(service_configs=SERVICE_CONFIGS)
    actions = wd.check_once()

    # Log all + send Telegram on restarts
    restarted = [a for a in actions if a.get("action") in ("restart", "restart_failed")]
    log_event({"actions": actions, "restarts": len(restarted)})

    if not quiet:
        summary_lines = []
        for a in actions:
            age = a.get("age_sec")
            age_str = f"{age:.0f}s" if isinstance(age, (int, float)) else "?"
            summary_lines.append(f"{a['service']:14} {a['action']:18} age={age_str} via={a.get('via') or '-'}")
        print("\n".join(summary_lines))
        if events := sum(1 for a in actions if a.get("action") == "ok"):
            print(f"\n[ok] {events} services healthy")

    if restarted:
        text = "[watchdog] restarted services:\n" + "\n".join(
            f"  {a['service']} → {a['action']} (via {a.get('via')}, age {a.get('age_sec'):.0f}s)"
            for a in restarted
        )
        send_telegram(text)

    return actions


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--loop", type=int, default=0, help="loop every N seconds (0 = single cycle)")
    p.add_argument("--quiet", action="store_true", help="suppress stdout output (cron-friendly)")
    args = p.parse_args()

    if args.loop <= 0:
        run_once(quiet=args.quiet)
        return 0

    while True:
        try:
            run_once(quiet=args.quiet)
        except Exception as e:
            print(f"watchdog loop error: {e}", file=sys.stderr)
        time.sleep(args.loop)


if __name__ == "__main__":
    sys.exit(main())