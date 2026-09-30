"""Per-service heartbeat writer + watchdog.

PHASE 6 FIX 2026-09-30: makes the system 24/7 by:
1. Each subsystem writes a heartbeat file to data_cache/heartbeat_<name>.json
   every 10s with ts, pid, uptime_sec, status.
2. The watchdog script (scripts/247_watchdog.py) checks all heartbeats
   every 30s. If any is stale (>90s old), the watchdog kills + restarts
   the corresponding NSSM service (or Start-Process if no NSSM).
3. Run the watchdog as a cron or as its own NSSM service.

This is the "non-glued" 24/7 piece. Without heartbeats, the kotak-bot-watchdog
cron can only check PROCESS aliveness — a process can be alive but stuck
(deadlocked on an LLM call, infinite WS reconnect loop, etc.). Heartbeats
catch that.

Usage from each service:
    from system.common.heartbeat import HeartbeatWriter
    hb = HeartbeatWriter("core_api", interval_sec=10)
    hb.start()  # spawns a background thread
    # ... main work ...
    # hb.stop() at shutdown

Usage from watchdog:
    from system.common.heartbeat import HeartbeatWatchdog
    wd = HeartbeatWatchdog(
        service_configs=[
            ("core_api", "KotakCoreAPI",      "system.core.api.server"),
            ("brain_bridge", "KotakBrainBridge",  "system.bridge.brain_bridge"),
            ("brain_daemon", "KotakBrainDaemon",  "system.brain.brain_daemon"),
            ("exec_gateway", "KotakExecGateway",  "system.exec.exec_gateway"),
        ],
        stale_threshold_sec=90,
    )
    wd.check_once()  # returns list of services that were restarted

Heartbeat file format (data_cache/heartbeat_<name>.json):
    {
        "service": "core_api",
        "pid": 1234,
        "started_at": "2026-09-30T13:00:00+05:30",
        "ts": "2026-09-30T13:35:30+05:30",
        "uptime_sec": 2130,
        "status": "ok" | "degraded" | "error",
        "last_error": "...",
        "counters": {"orders_placed": 12, "fills": 8}
    }
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


IST = timezone(timedelta(hours=5, minutes=30))
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
HEARTBEAT_DIR = PROJECT_ROOT / "data_cache"


def _now_ist_iso() -> str:
    return datetime.now(IST).isoformat()


class HeartbeatWriter:
    """Writes a heartbeat file every N seconds in a background thread.

    Thread-safe; uses an internal lock to swap status counters atomically.
    Exposes .update(**kwargs) so the calling service can report its own
    metrics (orders_placed, fills, errors, etc.) without touching the file
    directly.
    """

    def __init__(
        self,
        service_name: str,
        *,
        interval_sec: int = 10,
        heartbeat_dir: Path = HEARTBEAT_DIR,
    ):
        self.service_name = service_name
        self.interval_sec = max(5, int(interval_sec))
        self.path = heartbeat_dir / f"heartbeat_{service_name}.json"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.started_at = datetime.now(IST)
        self.status = "ok"
        self.last_error = ""
        self.counters: dict = {}

    def update(self, **kwargs) -> None:
        """Update counters / status / error. Thread-safe."""
        with self._lock:
            for k, v in kwargs.items():
                if k == "status":
                    self.status = str(v)
                elif k == "last_error":
                    self.last_error = str(v)
                else:
                    if not isinstance(v, (int, float, str, bool)):
                        v = str(v)
                    self.counters[k] = v

    def _write_file(self) -> None:
        from .atomic_io import write_json_atomic
        with self._lock:
            payload = {
                "service": self.service_name,
                "pid": os.getpid(),
                "started_at": self.started_at.isoformat(),
                "ts": _now_ist_iso(),
                "uptime_sec": int((datetime.now(IST) - self.started_at).total_seconds()),
                "status": self.status,
                "last_error": self.last_error,
                "counters": dict(self.counters),
            }
        write_json_atomic(self.path, payload)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_sec):
            try:
                self._write_file()
            except Exception as e:
                # Don't crash the main service for a heartbeat error
                print(f"[{self.service_name}] heartbeat write failed: {e}", flush=True)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name=f"hb-{self.service_name}", daemon=True)
        self._thread.start()
        # First heartbeat immediately
        try:
            self._write_file()
        except Exception:
            pass

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)


class HeartbeatWatchdog:
    """Checks heartbeats and restarts stale services.

    Restart strategy:
    1. Try `nssm restart <service>` (preferred — NSSM-managed).
    2. If NSSM not present / fails, fall back to `Start-Process python -m <module>`.

    The watchdog itself writes a heartbeat at `heartbeat_watchdog.json` so
    external monitoring (cron) can verify it's alive.
    """

    def __init__(
        self,
        *,
        service_configs: list[tuple[str, str, str]],
        # (service_name, nssm_service_name, python_module)
        stale_threshold_sec: int = 90,
        heartbeat_dir: Path = HEARTBEAT_DIR,
        python_exe: str = str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"),
    ):
        self.service_configs = service_configs
        self.stale_threshold_sec = stale_threshold_sec
        self.heartbeat_dir = heartbeat_dir
        self.python_exe = python_exe
        # nssm.exe path
        self.nssm = Path(r"C:\Tools\nssm\nssm-2.24\win64\nssm.exe")

    def _read_heartbeat(self, service_name: str) -> Optional[dict]:
        from .atomic_io import read_json
        return read_json(self.heartbeat_dir / f"heartbeat_{service_name}.json")

    def _age_sec(self, hb: dict) -> Optional[float]:
        ts_str = hb.get("ts", "")
        if not ts_str:
            return None
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=IST)
            else:
                dt = dt.astimezone(IST)
            return (datetime.now(IST) - dt).total_seconds()
        except Exception:
            return None

    def _restart_via_nssm(self, nssm_service: str) -> bool:
        if not self.nssm.exists():
            return False
        try:
            # Check service exists
            check = subprocess.run([str(self.nssm), "status", nssm_service], capture_output=True, text=True, timeout=5)
            if check.returncode != 0 and "does not exist" in (check.stdout + check.stderr).lower():
                return False
            # Restart
            r = subprocess.run([str(self.nssm), "restart", nssm_service], capture_output=True, text=True, timeout=10)
            return r.returncode == 0
        except Exception:
            return False

    def _restart_via_start_process(self, service_name: str, module: str) -> bool:
        try:
            args_by_svc = {
                "brain_bridge": ["--interval", "5"],
                "brain_daemon": ["--interval", "120"],
                "exec_gateway": ["--live"],
                "core_api": ["--db", "data_cache\\state.db", "--port", "8510"],
            }
            extra = args_by_svc.get(service_name, [])
            cmd = [self.python_exe, "-u", "-m", module, *extra]
            log_path = PROJECT_ROOT / "Logs" / f"{service_name}.out.log"
            err_path = PROJECT_ROOT / "Logs" / f"{service_name}.err.log"
            subprocess.Popen(
                cmd,
                cwd=str(PROJECT_ROOT),
                stdout=open(log_path, "ab"),
                stderr=open(err_path, "ab"),
                creationflags=0x00000008,  # DETACHED_PROCESS on Windows
            )
            return True
        except Exception:
            return False

    def check_once(self) -> list[dict]:
        """Check all heartbeats. Restart any that are stale.

        Returns a list of action records:
          [{"service": "...", "action": "restart"|"ok", "age_sec": N,
            "via": "nssm"|"start_process", "hb_status": "ok"|"degraded"|"error"}]
        """
        actions = []
        for service_name, nssm_service, module in self.service_configs:
            hb = self._read_heartbeat(service_name)
            action = {"service": service_name, "nssm_service": nssm_service, "module": module}

            if hb is None:
                action.update({"action": "no_heartbeat", "age_sec": None, "via": None})
                actions.append(action)
                continue

            age = self._age_sec(hb)
            hb_status = hb.get("status", "ok")

            if age is not None and age > self.stale_threshold_sec:
                # Stale → restart
                if self._restart_via_nssm(nssm_service):
                    action.update({"action": "restart", "via": "nssm", "age_sec": age, "hb_status": hb_status})
                elif self._restart_via_start_process(service_name, module):
                    action.update({"action": "restart", "via": "start_process", "age_sec": age, "hb_status": hb_status})
                else:
                    action.update({"action": "restart_failed", "via": None, "age_sec": age, "hb_status": hb_status})
            else:
                action.update({"action": "ok", "age_sec": age, "hb_status": hb_status})

            actions.append(action)
        return actions


if __name__ == "__main__":
    # Allow running as `python -m system.common.heartbeat` for manual check
    import sys
    wd = HeartbeatWatchdog(
        service_configs=[
            ("core_api", "KotakCoreAPI",      "system.core.api.server"),
            ("brain_bridge", "KotakBrainBridge",  "system.bridge.brain_bridge"),
            ("brain_daemon", "KotakBrainDaemon",  "system.brain.brain_daemon"),
            ("exec_gateway", "KotakExecGateway",  "system.exec.exec_gateway"),
        ],
    )
    results = wd.check_once()
    for r in results:
        print(json.dumps(r))
    sys.exit(0)