"""One-shot service repair probe - run as LocalSystem by the brain.

The 3 backup services (KotakBrainDaemon, KotakMavisRealtime = NSSM/paused;
KotakHttpServer = plain service/stopped) would not resume via sc continue.
This probe tries every strategy and logs exactly what each returns, so we
can see the real failure reason (e.g. the app crashes on start, or the
service is disabled, or NSSM re-pauses it).

Writes results to data_cache/service_repair_probe.json
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
OUT = ROOT / 'data_cache' / 'service_repair_probe.json'
NSSM = r'C:\Tools\nssm\nssm-2.24\win64\nssm.exe'

SERVICES = ["KotakBrainDaemon", "KotakMavisRealtime", "KotakHttpServer"]


def _run(cmd: list[str], timeout: int = 30) -> dict:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"cmd": " ".join(cmd), "exit": r.returncode,
                "out": (r.stdout or "")[:400], "err": (r.stderr or "")[:400]}
    except Exception as e:
        return {"cmd": " ".join(cmd), "exit": None, "err": str(e)[:200]}


def _state(svc: str) -> str:
    r = subprocess.run(["sc", "query", svc], capture_output=True, text=True, timeout=20)
    for line in r.stdout.splitlines():
        if "STATE" in line:
            return line.split(":")[-1].strip().split()[-1]
    return "?"


def _qc(svc: str) -> dict:
    """Query the service config (start type, binary path)."""
    r = subprocess.run(["sc", "qc", svc], capture_output=True, text=True, timeout=20)
    d = {}
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("START_TYPE"):
            d["start_type"] = line.split(":", 1)[1].strip() if ":" in line else line
        if line.startswith("BINARY_PATH_NAME"):
            d["binpath"] = line.split(":", 1)[1].strip() if ":" in line else line
    return d


def main() -> int:
    results = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"),
               "is_admin": _is_admin(), "services": {}}
    for svc in SERVICES:
        before = _state(svc)
        entry = {"before": before, "qc": _qc(svc), "attempts": []}
        # Strategy 1: sc continue (for PAUSED)
        if before == "PAUSED":
            entry["attempts"].append(_run(["sc", "continue", svc]))
            entry["after_continue"] = _state(svc)
        # Strategy 2: nssm start (for STOPPED or if still paused)
        if _state(svc) in ("PAUSED", "STOPPED"):
            entry["attempts"].append(_run([NSSM, "start", svc]))
            entry["after_nssm_start"] = _state(svc)
        # Strategy 3: sc start
        if _state(svc) in ("PAUSED", "STOPPED"):
            entry["attempts"].append(_run(["sc", "start", svc]))
            entry["after_sc_start"] = _state(svc)
        entry["final"] = _state(svc)
        results["services"][svc] = entry
    try:
        OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"write err: {e}")
    return 0


def _is_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
