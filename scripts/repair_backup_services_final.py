"""Final repair for the 2 safe backup services (run as LocalSystem by the brain).

Findings:
  - KotakMavisRealtime: sc stop OK -> nssm start says success -> but the
    service returns to PAUSED. Some state machine re-pauses it. Try a clean
    sc stop then direct sc start (bypassing nssm's paused-state tracking).
  - KotakHttpServer: it is a PLAIN service (binary = powershell.exe), so the
    SCM gets no SetServiceStatus and start fails 1053. Fix = re-register it
    as an NSSM-managed service wrapping the python http_server, so NSSM
    reports status. Reversible: the original powershell binpath is recorded.

KotakBrainDaemon is NOT touched (double-trade risk).

Writes data_cache/backup_services_final.json
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
OUT = ROOT / 'data_cache' / 'backup_services_final.json'
NSSM = r'C:\Tools\nssm\nssm-2.24\win64\nssm.exe'
PY = str(ROOT / '.venv' / 'Scripts' / 'python.exe')
HTTP_ARGS = '-u -m kotak_bot.http_server --port 8502'


def _run(cmd, timeout=40):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"cmd": " ".join(cmd), "exit": r.returncode,
                "out": (r.stdout or "").strip()[:400],
                "err": (r.stderr or "").strip()[:400]}
    except Exception as e:
        return {"cmd": " ".join(cmd), "exit": None, "err": str(e)[:200]}


def _state(svc):
    r = subprocess.run(["sc", "query", svc], capture_output=True, text=True, timeout=20)
    for line in r.stdout.splitlines():
        if "STATE" in line:
            return line.split(":")[-1].strip().split()[-1]
    return "?"


def repair_mavis():
    """Clean stop then direct sc start (bypass nssm paused tracking)."""
    e = {"before": _state("KotakMavisRealtime"), "steps": []}
    e["steps"].append(_run(["sc", "stop", "KotakMavisRealtime"]))
    for _ in range(6):
        if _state("KotakMavisRealtime") == "STOPPED":
            break
        time.sleep(2)
    e["after_stop"] = _state("KotakMavisRealtime")
    e["steps"].append(_run(["sc", "start", "KotakMavisRealtime"]))
    time.sleep(5)
    e["after_sc_start"] = _state("KotakMavisRealtime")
    e["final"] = _state("KotakMavisRealtime")
    return e


def repair_http():
    """Re-register as NSSM service so the SCM gets status reports."""
    e = {"before": _state("KotakHttpServer"), "steps": []}
    # Record the current binpath so the change is reversible.
    qc = subprocess.run(["sc", "qc", "KotakHttpServer"], capture_output=True, text=True, timeout=20)
    for line in qc.stdout.splitlines():
        if "BINARY_PATH_NAME" in line:
            e["original_binpath"] = line.split(":", 1)[1].strip()
    if _state("KotakHttpServer") != "STOPPED":
        e["steps"].append(_run(["sc", "stop", "KotakHttpServer"]))
        time.sleep(3)
    # Remove the plain service, re-install under NSSM.
    e["steps"].append(_run([NSSM, "remove", "KotakHttpServer", "confirm"]))
    time.sleep(2)
    e["steps"].append(_run([NSSM, "install", "KotakHttpServer", PY, HTTP_ARGS]))
    e["steps"].append(_run([NSSM, "set", "KotakHttpServer", "AppDirectory", str(ROOT)]))
    e["steps"].append(_run([NSSM, "set", "KotakHttpServer", "Start", "SERVICE_AUTO_START"]))
    e["steps"].append(_run([NSSM, "set", "KotakHttpServer", "AppStdout", str(ROOT / "Logs" / "http_server_stdout.log")]))
    e["steps"].append(_run([NSSM, "set", "KotakHttpServer", "AppStderr", str(ROOT / "Logs" / "http_server_stderr.log")]))
    e["steps"].append(_run([NSSM, "start", "KotakHttpServer"]))
    time.sleep(6)
    e["after_nssm_start"] = _state("KotakHttpServer")
    e["final"] = _state("KotakHttpServer")
    return e


def main() -> int:
    results = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"),
               "note": "KotakBrainDaemon excluded (double-trade risk)",
               "services": {}}
    results["services"]["KotakMavisRealtime"] = repair_mavis()
    results["services"]["KotakHttpServer"] = repair_http()
    try:
        OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"write err: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
