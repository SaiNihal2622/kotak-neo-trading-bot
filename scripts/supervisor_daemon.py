"""supervisor_daemon.py — SYSTEM-context watchdog for the Kotak Neo bot.

The "always on" layer that runs even if the user is away. Checks every
30 seconds that:
  1. NSSM service KotakBotPaper is RUNNING — start if not
  2. NSSM service KotakQuantService is RUNNING — start if not
  3. Bot liveness is fresh (liveness.json updated in <3 min) — restart via NSSM
  4. Brain HTTP :8503 is responding — alert if not

Runs as a SYSTEM scheduled task via:
  schtasks /create /tn KotakSupervisor /tr "C:\\path\\to\\.venv\\python.exe supervisor_daemon.py" /sc ONSTART /ru SYSTEM /rl HIGHEST /f

Why Python, not PowerShell:
  - Avoids PowerShell $pid/$PID read-only variable confusion
  - No parsing/quoting issues with command-line arguments
  - Cross-platform if you ever move to Linux
  - Easier to test

Run as a foreground process (intended to be launched by schtasks):
  python scripts/supervisor_daemon.py
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
DCACHE = ROOT / "data_cache"
LOGS = ROOT / "Logs"
NSSM_EXE = Path(r"C:\Tools\nssm\nssm-2.24\win64\nssm.exe")
LOG_FILE = LOGS / "supervisor_daemon.log"
CHECK_INTERVAL_SEC = 30
STALE_THRESHOLD_SEC = 180  # 3 min

LOGS.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("supervisor")


def _sc_query(service: str) -> str:
    """Return NSSM service status via sc query. Returns 'RUNNING'|'STOPPED'|...|'UNKNOWN'."""
    try:
        r = subprocess.run(
            ["sc", "query", service],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return "UNKNOWN"
        out = (r.stdout or "").upper()
        for state in ("RUNNING", "STOPPED", "START_PENDING", "STOP_PENDING"):
            if f"STATE              : 4  {state}" in out or f"STATE              : 1  {state}" in out:
                return state
        return "UNKNOWN"
    except Exception as e:
        log.error(f"sc query {service} failed: {e}")
        return "UNKNOWN"


def _nssm_start(service: str) -> bool:
    """Try to start an NSSM service. Returns True on success."""
    try:
        r = subprocess.run(
            [str(NSSM_EXE), "start", service],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode == 0:
            log.info(f"[supervisor] nssm start {service} OK")
            return True
        else:
            log.warning(f"[supervisor] nssm start {service} failed exit={r.returncode}: {(r.stdout or r.stderr or '').strip()[:200]}")
            return False
    except Exception as e:
        log.error(f"nssm start {service} exception: {e}")
        return False


def _nssm_restart(service: str) -> bool:
    """Try to restart an NSSM service."""
    try:
        r = subprocess.run(
            [str(NSSM_EXE), "restart", service],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            log.info(f"[supervisor] nssm restart {service} OK")
            return True
        else:
            log.warning(f"[supervisor] nssm restart {service} failed exit={r.returncode}: {(r.stdout or r.stderr or '').strip()[:200]}")
            return False
    except Exception as e:
        log.error(f"nssm restart {service} exception: {e}")
        return False


def _bot_liveness() -> dict:
    """Read liveness.json. Returns dict with 'pid', 'age_sec', 'state'."""
    liv = DCACHE / "liveness.json"
    if not liv.exists():
        return {"pid": None, "age_sec": 999999, "state": "missing"}
    try:
        d = json.loads(liv.read_text(encoding="utf-8"))
        ts_str = d.get("ts", "")
        if not ts_str:
            return {"pid": d.get("pid"), "age_sec": 999999, "state": "no_ts"}
        # ISO format like 2026-09-08T01:38:25.123456+05:30
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        return {"pid": d.get("pid"), "age_sec": age, "state": d.get("state", "?")}
    except Exception as e:
        return {"pid": None, "age_sec": 999999, "state": f"unparseable: {e}"}


def _brain_alive() -> bool:
    """Check if brain HTTP :8503 responds."""
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8503/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _is_alive(pid: int | None) -> bool:
    """Check if a process with this PID is running."""
    if not pid:
        return False
    try:
        # Use WMI for SYSTEM-context processes too
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"Get-Process -Id {pid} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
            capture_output=True, text=True, timeout=5,
        )
        return (r.stdout or "").strip() == str(pid)
    except Exception:
        return False


def _send_telegram(msg: str) -> bool:
    try:
        cred = ROOT / "config" / "credentials.env"
        for line in cred.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
        sys.path.insert(0, str(ROOT / "scripts"))
        from telegram_alerter import get_alerter
        a = get_alerter()
        if a and a.enabled:
            return a.send(msg)
    except Exception as e:
        log.debug(f"telegram send failed: {e}")
    return False


def run_cycle(cycle: int) -> None:
    """One supervisor iteration."""
    log.info(f"[supervisor] cycle={cycle} start")
    # 1. NSSM KotakBotPaper
    bot_nssm = _sc_query("KotakBotPaper")
    log.info(f"[supervisor] cycle={cycle} KotakBotPaper nssm={bot_nssm}")
    if bot_nssm != "RUNNING":
        log.warning(f"[supervisor] cycle={cycle} KotakBotPaper NSSM is {bot_nssm} - starting")
        if not _nssm_start("KotakBotPaper"):
            # Last resort: start a direct python bot as SYSTEM
            log.warning(f"[supervisor] cycle={cycle} NSSM start failed, falling back to direct start")
            py = ROOT / ".venv" / "Scripts" / "python.exe"
            try:
                subprocess.Popen(
                    [str(py), "-m", "kotak_bot", "paper"],
                    cwd=str(ROOT),
                    creationflags=0x00000008,  # DETACHED_PROCESS
                )
            except Exception as e:
                log.error(f"[supervisor] direct start failed: {e}")

    # 2. NSSM KotakQuantService
    brain_nssm = _sc_query("KotakQuantService")
    if brain_nssm not in ("RUNNING", "START_PENDING"):
        log.warning(f"[supervisor] cycle={cycle} KotakQuantService NSSM is {brain_nssm} - starting")
        _nssm_start("KotakQuantService")

    # 3. Bot liveness freshness
    time.sleep(5)  # let the bot write liveness after a restart
    liv = _bot_liveness()
    if liv["age_sec"] > STALE_THRESHOLD_SEC:
        log.warning(f"[supervisor] cycle={cycle} liveness stale (age={int(liv['age_sec'])}s, pid={liv['pid']}) - restarting bot")
        if _nssm_restart("KotakBotPaper"):
            _send_telegram(f"[Mavis supervisor] bot liveness stale (age={int(liv['age_sec'])}s), restarted via NSSM")
        else:
            _send_telegram(f"[Mavis supervisor] bot liveness stale (age={int(liv['age_sec'])}s), nssm restart FAILED")

    # 4. Process actually alive (separate check)
    if not _is_alive(liv["pid"]):
        log.warning(f"[supervisor] cycle={cycle} bot PID {liv['pid']} is not running but liveness says {liv['state']} - restarting")
        _nssm_restart("KotakBotPaper")

    # 5. Brain port
    if not _brain_alive():
        log.warning(f"[supervisor] cycle={cycle} brain port 8503 not responding")

    # 6. Verbose status every 10 min
    if cycle % 20 == 0:
        log.info(
            f"[supervisor] cycle={cycle} OK | "
            f"bot_nssm={bot_nssm} | brain_nssm={brain_nssm} | "
            f"bot_pid={liv['pid']} | liveness_age={int(liv['age_sec'])}s | "
            f"brain_port={_brain_alive()}"
        )


def main() -> int:
    log.info("=" * 50)
    log.info(f"[supervisor] starting (interval={CHECK_INTERVAL_SEC}s, stale={STALE_THRESHOLD_SEC}s)")
    try:
        import os
        ctx = os.environ.get("USERNAME", "?")
        sid = os.environ.get("SESSIONNAME", "?")
        log.info(f"[supervisor] context: USERNAME={ctx} SESSIONNAME={sid}")
    except Exception:
        pass
    cycle = 0
    while True:
        cycle += 1
        try:
            run_cycle(cycle)
        except Exception as e:
            log.error(f"[supervisor] cycle={cycle} exception: {e}")
        time.sleep(CHECK_INTERVAL_SEC)


if __name__ == "__main__":
    sys.exit(main())
