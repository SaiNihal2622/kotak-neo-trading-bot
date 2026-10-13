"""Repair the 2 SAFE backup services (run as LocalSystem by the brain).

Decision (2026-10-13): do NOT start KotakBrainDaemon — it is a second
trading brain that writes to the SAME data_cache/quant_actions.json the
main brain (KotakQuantService) writes and the bridge executes, with no
failover guard. Starting it = two brains issuing orders = double trades.
It stays paused by design.

Start these 2 (safe):
  - KotakMavisRealtime : event monitor (writes mavis_events.jsonl, no orders)
  - KotakHttpServer    : read-only monitoring endpoint on :8502

Both are PAUSED/STOPPED and won't resume via sc continue (stuck in
CONTINUE_PENDING). Strategy: force-stop the hung process, then start fresh.

Writes data_cache/backup_services_repair.json
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
OUT = ROOT / 'data_cache' / 'backup_services_repair.json'
NSSM = r'C:\Tools\nssm\nssm-2.24\win64\nssm.exe'

# KotakBrainDaemon intentionally EXCLUDED (double-trade risk).
SAFE_SERVICES = ["KotakMavisRealtime", "KotakHttpServer"]


def _run(cmd, timeout=40):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"cmd": " ".join(cmd), "exit": r.returncode,
                "out": (r.stdout or "").strip()[:300],
                "err": (r.stderr or "").strip()[:300]}
    except Exception as e:
        return {"cmd": " ".join(cmd), "exit": None, "err": str(e)[:200]}


def _state(svc):
    r = subprocess.run(["sc", "query", svc], capture_output=True, text=True, timeout=20)
    for line in r.stdout.splitlines():
        if "STATE" in line:
            return line.split(":")[-1].strip().split()[-1]
    return "?"


def _repair(svc):
    entry = {"before": _state(svc), "steps": []}
    # If PAUSED or STOPPING, force stop first (a paused service accepts STOP).
    if _state(svc) in ("PAUSED", "STOPPING", "CONTINUE_PENDING", "START_PENDING"):
        entry["steps"].append(_run(["sc", "stop", svc]))
        time.sleep(3)
        entry["after_stop"] = _state(svc)
    # If still not stopped, kill via nssm (kills the process tree).
    if _state(svc) != "STOPPED":
        entry["steps"].append(_run([NSSM, "stop", svc]))
        time.sleep(3)
        entry["after_nssm_stop"] = _state(svc)
    # Start fresh.
    entry["steps"].append(_run([NSSM, "start", svc]))
    time.sleep(4)
    entry["after_nssm_start"] = _state(svc)
    if _state(svc) != "RUNNING":
        entry["steps"].append(_run(["sc", "start", svc]))
        time.sleep(4)
        entry["after_sc_start"] = _state(svc)
    entry["final"] = _state(svc)
    return entry


def main() -> int:
    results = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"),
               "note": "KotakBrainDaemon deliberately excluded (double-trade risk)",
               "services": {}}
    for svc in SAFE_SERVICES:
        results["services"][svc] = _repair(svc)
    try:
        OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"write err: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
