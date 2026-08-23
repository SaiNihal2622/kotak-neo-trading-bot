"""HTTP server watchdog — ensures the production HTTP server stays up.

Runs every 5 minutes via kotak-http-watchdog cron. If the HTTP server
isn't responding on :8502, restart it. This is the production-grade
fallback for the brittle Windows-service registration.

Public use:
  python scripts/http_server_watchdog.py            # check + restart if down
  python scripts/http_server_watchdog.py --dry-run  # check only, no restart
  python scripts/http_server_watchdog.py --port 8502
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def is_listening(host: str, port: int, timeout: float = 3.0) -> bool:
    """Return True if something is listening on host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def probe_health(port: int, timeout: float = 5.0) -> tuple[bool, int, str]:
    """Return (ok, http_status, body_preview)."""
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="ignore")
            ok = r.status == 200 and '"ok": true' in body
            return ok, r.status, body[:200]
    except urllib.error.HTTPError as e:
        # Non-2xx response — still useful data, capture status + body
        try:
            body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            body = ""
        ok = False
        return ok, e.code, body[:200]
    except Exception as e:
        return False, 0, f"error: {e}"


def restart_server(port: int) -> int:
    """Start the HTTP server in the background. Returns the launched PID."""
    py = ROOT / ".venv" / "Scripts" / "python.exe"
    out_log = ROOT / "Logs" / "http_server.out"
    err_log = ROOT / "Logs" / "http_server.err"
    out_log.parent.mkdir(parents=True, exist_ok=True)
    # Run via powershell so the process inherits a stable environment.
    # We use Start-Process so it detaches from this watchdog's process tree.
    ps_script = (
        f"$p = Start-Process -FilePath '{py}' "
        f"-ArgumentList @('-u', '-m', 'kotak_bot.http_server', '--port', '{port}') "
        f"-WorkingDirectory '{ROOT}' "
        f"-RedirectStandardOutput '{out_log}' "
        f"-RedirectStandardError '{err_log}' "
        f"-WindowStyle Hidden -PassThru; "
        f"Write-Output $p.Id"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        capture_output=True, text=True, timeout=15,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"failed to start http server: {proc.stderr.strip()}")
    pid = int(proc.stdout.strip().splitlines()[-1])
    return pid


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8502)
    p.add_argument("--dry-run", action="store_true", help="check only, no restart")
    args = p.parse_args()

    listening = is_listening(args.host, args.port, timeout=2.0)
    if not listening:
        if args.dry_run:
            print(f"[watchdog] DOWN: nothing listening on {args.host}:{args.port} (dry-run)")
            return 1
        print(f"[watchdog] DOWN: nothing on {args.host}:{args.port}, starting…")
        try:
            pid = restart_server(args.port)
            print(f"[watchdog] launched PID {pid}, waiting 3s for it to bind…")
            time.sleep(3.0)
        except Exception as e:
            print(f"[watchdog] RESTART FAILED: {e}")
            return 2
    # Now check /health
    ok, status, body = probe_health(args.port, timeout=5.0)
    ts = datetime.now().isoformat(timespec="seconds")
    record = {"ts": ts, "host": args.host, "port": args.port, "ok": ok, "http": status, "body": body}
    out = ROOT / "data_cache" / "http_watchdog.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    if ok:
        print(f"[watchdog] OK: http {status}, body preview: {body[:80]}")
        return 0
    else:
        print(f"[watchdog] DEGRADED: http {status} body={body[:80]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
