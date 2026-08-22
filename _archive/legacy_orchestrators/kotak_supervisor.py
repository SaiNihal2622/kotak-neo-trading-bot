"""Kotak Supervisor — the topmost layer for 24/7 uptime.

This is the "outer ring" of supervision. Below it:
  - kotak_orchestrator.py supervises kotak_healer.py + brain ticks
  - kotak_healer.py supervises kotak_bot.py
  - kotak_executor.py runs the paper-trade execution loop

This supervisor watches ALL of them and re-launches anything that dies.
A separate VBS wrapper (supervisor_wrapper.vbs) re-launches THIS process
if it itself dies, giving us two layers of "process resurrection" without
needing admin rights or NSSM.

Supervision targets (checked every 30s):
  1. kotak_orchestrator.py   — must always be alive
  2. kotak_executor.py        — must always be alive
  3. kotak_bot.py             — main trading bot (also supervised by healer)
  4. dashboard (port 8501)    — streamlit dashboard, HTTP 200 check

PID lock so only one supervisor runs at a time. Logs to logs/supervisor.log.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

from loguru import logger  # noqa: E402

SUP_LOG_PATH = ROOT / "logs" / "supervisor.log"
SUP_STATE_PATH = ROOT / "data_cache" / "supervisor_state.json"

SUPERVISE_INTERVAL_SEC = 30      # main loop tick
DASHBOARD_URL = "http://127.0.0.1:8501"
DASHBOARD_HEALTH_TIMEOUT = 5     # seconds
MAX_BACKOFF_SEC = 60             # cap restart backoff per target

PYTHON_EXE = sys.executable

# Targets we supervise. Each entry has:
#   name:        logical name for logging
#   pidfile:     optional pidfile to check (preferred over WMI scan)
#   match:       substring to find in python command line (for liveness check)
#   spawn_args:  list of args to pass to [PYTHON_EXE, "-u", *spawn_args] for relaunch
#   essential:   whether this target must be alive for the system to function
TARGETS = [
    {
        "name": "orchestrator",
        "pidfile": ROOT / "data_cache" / "orchestrator.pid",
        "match": "kotak_orchestrator.py",
        "spawn_args": ["kotak_orchestrator.py"],
        "essential": True,
    },
    {
        "name": "executor",
        "pidfile": ROOT / "data_cache" / "executor.pid",
        "match": "kotak_executor.py",
        "spawn_args": ["kotak_executor.py"],
        "essential": True,
    },
    {
        "name": "bot",
        # bot doesn't keep a pidfile; identify by command line containing "kotak_bot"
        "pidfile": None,
        "match": "kotak_bot",
        # Original launch command is `python -u -m kotak_bot paper`
        "spawn_args": ["-m", "kotak_bot", "paper"],
        "essential": True,
    },
]


def _save_state(state: dict) -> None:
    try:
        SUP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = SUP_STATE_PATH.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            import json
            json.dump(state, f, indent=2, default=str)
        tmp.replace(SUP_STATE_PATH)
    except Exception as e:
        logger.warning(f"sup: cannot save state: {e}")


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        import psutil  # type: ignore
        return psutil.pid_exists(pid)
    except ImportError:
        # Fallback: try os.kill(pid, 0) — Windows raises OSError if dead
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def _wmi_pids_by_script(script_name: str) -> list[int]:
    """Return PIDs of python.exe whose command line contains script_name.

    Excludes this supervisor's own command line and any start_*_daemons.ps1 calls.
    """
    pids: list[int] = []
    try:
        import win32com.client  # type: ignore
        wmi = win32com.client.GetObject("winmgmts:")
        procs = wmi.InstancesOf("Win32_Process")
        my_pid = os.getpid()
        for p in procs:
            try:
                if p.Name and p.Name.lower() == "python.exe":
                    if p.ProcessId == my_pid:
                        continue
                    cl = p.CommandLine or ""
                    if script_name in cl and "start_24x7" not in cl and "kotak_supervisor" not in cl:
                        pids.append(int(p.ProcessId))
            except Exception:
                continue
    except ImportError:
        # No WMI module — fall back to tasklist parsing (less reliable)
        try:
            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/V"],
                capture_output=True, text=True, timeout=10,
            )
            for line in r.stdout.splitlines():
                if script_name in line and "kotak_supervisor" not in line:
                    # CSV format: "Name","PID","SessionName","SessionNum","MemUsage","Status","UserName","WindowTitle","CPUTime"
                    parts = line.split('","')
                    if len(parts) >= 2:
                        try:
                            pid = int(parts[1].strip('"'))
                            pids.append(pid)
                        except ValueError:
                            pass
        except Exception:
            pass
    return pids


def _pidfile_alive(pidfile: Path | None) -> tuple[bool, int | None]:
    """Check if the PID in a pidfile is still alive."""
    if not pidfile or not pidfile.exists():
        return False, None
    try:
        pid = int(pidfile.read_text().strip() or "0")
    except (ValueError, OSError):
        return False, None
    if pid <= 0:
        return False, None
    return _pid_alive(pid), pid


def _launch_target(target: dict) -> int | None:
    """Spawn the target as a detached child. Returns new PID or None."""
    spawn_args = target.get("spawn_args", [])
    # Validate any script-path arg resolves to an existing file.
    for arg in spawn_args:
        if arg.endswith(".py"):
            candidate = ROOT / arg
            if not candidate.exists():
                logger.error(f"sup: cannot launch {target['name']}: script missing at {candidate}")
                return None
    try:
        # Use CREATE_NO_WINDOW + DETACHED_PROCESS for full background.
        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        flags = DETACHED_PROCESS | CREATE_NO_WINDOW
        p = subprocess.Popen(
            [PYTHON_EXE, "-u", *spawn_args],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
        logger.info(f"sup: launched {target['name']} pid={p.pid} (args={' '.join(spawn_args)})")
        return p.pid
    except Exception as e:
        logger.exception(f"sup: failed to launch {target['name']}: {e}")
        return None


def _check_dashboard() -> bool:
    """Check if dashboard is responding on port 8501."""
    try:
        req = urllib.request.Request(DASHBOARD_URL, method="GET")
        with urllib.request.urlopen(req, timeout=DASHBOARD_HEALTH_TIMEOUT) as r:
            return 200 <= r.status < 400
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError):
        return False


def _find_dashboard_pid() -> int | None:
    """Find streamlit process for the dashboard."""
    pids = _wmi_pids_by_script("dashboard_app.py")
    if pids:
        return pids[0]
    # Also check for streamlit processes
    pids = _wmi_pids_by_script("streamlit")
    return pids[0] if pids else None


def _launch_dashboard() -> int | None:
    """Launch the streamlit dashboard."""
    dash_script = ROOT / "dashboard_app.py"
    if not dash_script.exists():
        logger.warning(f"sup: dashboard_app.py not found at {dash_script}")
        return None
    try:
        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        flags = DETACHED_PROCESS | CREATE_NO_WINDOW
        p = subprocess.Popen(
            [PYTHON_EXE, "-u", "-m", "streamlit", "run", str(dash_script),
             "--server.port=8501", "--server.headless=true",
             "--server.address=127.0.0.1", "--browser.gatherUsageStats=false"],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
        logger.info(f"sup: launched dashboard pid={p.pid}")
        return p.pid
    except Exception as e:
        logger.exception(f"sup: failed to launch dashboard: {e}")
        return None


def _supervise_once(state: dict) -> dict:
    """One supervision tick. Returns updated state."""
    now_iso = datetime.now().isoformat() + "+00:00"
    state["last_tick"] = now_iso
    state["tick_count"] = int(state.get("tick_count", 0)) + 1
    restarts = state.setdefault("restarts", {})
    state.setdefault("last_attempt", {})

    for target in TARGETS:
        name = target["name"]
        match = target["match"]
        if target["pidfile"]:
            alive, pid = _pidfile_alive(target["pidfile"])
        else:
            # bot — find by command line
            pids = _wmi_pids_by_script(match)
            alive = len(pids) > 0
            pid = pids[0] if pids else None

        state.setdefault("alive", {})[name] = alive
        state.setdefault("pid", {})[name] = pid

        if not alive:
            backoff = min(MAX_BACKOFF_SEC, 2 ** min(restarts.get(name, 0), 5))
            last_attempt = state.get("last_attempt", {}).get(name, 0)
            if (time.time() - last_attempt) < backoff:
                continue  # still in backoff window
            state.setdefault("last_attempt", {})[name] = time.time()
            logger.warning(
                f"sup: {name} (match={match}) is DOWN, "
                f"attempting relaunch (attempt #{restarts.get(name, 0) + 1})"
            )
            new_pid = _launch_target(target)
            restarts[name] = restarts.get(name, 0) + 1
            state["pid"][name] = new_pid
            state["alive"][name] = new_pid is not None
        else:
            # Reset backoff if it was alive
            if restarts.get(name, 0) > 0:
                logger.info(f"sup: {name} is alive again (pid={pid}), reset backoff")
            restarts[name] = 0
            state["last_attempt"].pop(name, None)

    # Dashboard — separate logic (HTTP-based)
    dash_alive = _check_dashboard()
    state["alive"]["dashboard"] = dash_alive
    if dash_alive:
        dash_pid = _find_dashboard_pid()
        state["pid"]["dashboard"] = dash_pid
        restarts["dashboard"] = 0
    else:
        # backoff
        backoff = min(MAX_BACKOFF_SEC, 2 ** min(restarts.get("dashboard", 0), 5))
        last_attempt = state.get("last_attempt", {}).get("dashboard", 0)
        if (time.time() - last_attempt) >= backoff:
            state.setdefault("last_attempt", {})["dashboard"] = time.time()
            logger.warning(f"sup: dashboard is DOWN on {DASHBOARD_URL}, attempting relaunch")
            new_pid = _launch_dashboard()
            restarts["dashboard"] = restarts.get("dashboard", 0) + 1
            state["pid"]["dashboard"] = new_pid

    _save_state(state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true",
                        help="Run a single supervision tick then exit")
    parser.add_argument("--interval", type=int, default=SUPERVISE_INTERVAL_SEC,
                        help=f"Tick interval in seconds (default: {SUPERVISE_INTERVAL_SEC})")
    args = parser.parse_args()

    SUP_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger.remove()  # remove default stderr handler
    logger.add(str(SUP_LOG_PATH), rotation="1 day", retention="14 days", level="INFO")
    logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>")
    logger.info(f"sup: starting (once={args.once}, interval={args.interval}s) pid={os.getpid()}")

    # PID lock — prevent multiple supervisors
    pidfile = ROOT / "data_cache" / "supervisor.pid"
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    if pidfile.exists():
        try:
            old = int(pidfile.read_text().strip() or "0")
            if old and old != os.getpid() and _pid_alive(old):
                logger.warning(f"sup: another supervisor alive pid={old}, exiting")
                return 0
        except Exception:
            pass
    pidfile.write_text(str(os.getpid()))

    try:
        state: dict = {}
        if args.once:
            _supervise_once(state)
            logger.info("sup: --once complete")
            return 0

        import signal as _signal
        stop = False

        def _sigint(_sig, _frm):
            nonlocal stop
            stop = True
            logger.info("sup: SIGINT received, shutting down")
        try:
            _signal.signal(_signal.SIGINT, _sigint)
        except Exception:
            pass
        try:
            _signal.signal(_signal.SIGTERM, _sigint)
        except Exception:
            pass

        # On startup, do an immediate tick to recover anything that died while we were off
        logger.info("sup: initial tick to bring any dead targets back up")
        _supervise_once(state)

        while not stop:
            try:
                _supervise_once(state)
            except Exception as e:
                logger.exception(f"sup: tick exception: {e}")
            for _ in range(args.interval):
                if stop:
                    break
                time.sleep(1)
        return 0
    finally:
        try:
            if int(pidfile.read_text().strip() or "0") == os.getpid():
                pidfile.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
