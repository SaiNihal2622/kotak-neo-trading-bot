"""Fix KotakMavisRealtime: bad AppDirectory made the app path unresolvable.

Bug: NSSM AppDirectory = .venv\\Scripts but AppParameters = relative
"scripts\\mavis_realtime.py" -> resolves to .venv\\Scripts\\scripts\\
mavis_realtime.py (does not exist) -> the app never starts -> the service
never leaves PAUSED. Fix: set AppDirectory to the project root (same as the
working KotakHttpServer service), then start.

Writes data_cache/mavis_fix.json
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
OUT = ROOT / 'data_cache' / 'mavis_fix.json'
NSSM = r'C:\Tools\nssm\nssm-2.24\win64\nssm.exe'


def _run(cmd, timeout=40):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"cmd": " ".join(cmd), "exit": r.returncode,
                "out": (r.stdout or "").strip()[:300], "err": (r.stderr or "").strip()[:300]}
    except Exception as e:
        return {"cmd": " ".join(cmd), "exit": None, "err": str(e)[:200]}


def _state(svc):
    r = subprocess.run(["sc", "query", svc], capture_output=True, text=True, timeout=20)
    for line in r.stdout.splitlines():
        if "STATE" in line:
            return line.split(":")[-1].strip().split()[-1]
    return "?"


def main() -> int:
    svc = "KotakMavisRealtime"
    e = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"),
         "before": _state(svc), "steps": []}
    # Stop cleanly.
    e["steps"].append(_run(["sc", "stop", svc]))
    for _ in range(8):
        if _state(svc) == "STOPPED":
            break
        time.sleep(2)
    e["after_stop"] = _state(svc)
    # FIX: correct AppDirectory to the project root.
    e["steps"].append(_run([NSSM, "set", svc, "AppDirectory", str(ROOT)]))
    # Ensure the exact interpreter + absolute param (belt and braces).
    e["steps"].append(_run([NSSM, "set", svc, "Application", str(ROOT / ".venv" / "Scripts" / "python.exe")]))
    e["steps"].append(_run([NSSM, "set", svc, "AppParameters", "-u scripts\\mavis_realtime.py"]))
    # Start.
    e["steps"].append(_run([NSSM, "start", svc]))
    time.sleep(8)
    e["after_start"] = _state(svc)
    e["final"] = _state(svc)
    try:
        OUT.write_text(json.dumps(e, indent=2), encoding="utf-8")
    except Exception as ex:
        print(f"write err: {ex}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
