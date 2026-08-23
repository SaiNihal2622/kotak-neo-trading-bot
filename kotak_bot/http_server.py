"""Production-grade stdlib HTTP server for the Kotak bot.

Exposes three endpoints for external monitoring / dashboards / alerting:

  GET /health   → 200 "ok" if the bot is alive and state is running
                  503 "degraded" if state != running or liveness stale
                  Body: JSON with liveness snapshot
  GET /metrics  → Prometheus text format (counters/gauges/timings)
  GET /status   → Detailed JSON: liveness + paper state + audit summary +
                  circuit breakers + risk state

Run as a sidecar:
  python -m kotak_bot.http_server --port 8502

Why stdlib
----------
No new dependency. ``http.server`` + ``socketserver`` are enough. Production
deployments that need async/concurrency should swap to ``aiohttp`` or
``uvicorn``, but for a few-requests-per-minute health endpoint, stdlib
is simpler and bulletproof.

Caching
-------
The /metrics endpoint re-renders on every request (cheap; ~1ms). The
/health and /status endpoints read from disk, so they're slightly more
expensive (~5-10ms). If you need to handle hundreds of req/sec, swap
this for an in-process state read.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

# Make the project importable when this is run as a module
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _read_liveness() -> dict:
    p = ROOT / "data_cache" / "liveness.json"
    if not p.exists():
        return {"available": False, "reason": "missing"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data["ts"])
        if ts.tzinfo is None:
            ts = ts.astimezone()
        age_sec = (datetime.now(timezone.utc).astimezone() - ts).total_seconds()
        return {"available": True, "age_sec": round(age_sec, 1), **data}
    except Exception as e:
        return {"available": False, "reason": f"parse: {e}"}


def _read_paper_state() -> dict:
    p = ROOT / "data_cache" / "paper_state.json"
    if not p.exists():
        return {"available": False}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {
            "available": True,
            "cash": data.get("cash", 0),
            "realized_pnl": data.get("realized_pnl", 0),
            "open_positions": len(data.get("positions", [])) if isinstance(data.get("positions"), list) else 0,
            "open_orders": len(data.get("orders", {})),
        }
    except Exception:
        return {"available": False}


def _read_audit_summary() -> dict:
    p = ROOT / "data_cache" / "audit.jsonl"
    if not p.exists():
        return {"available": False, "total": 0}
    try:
        from kotak_bot.utils.audit import AuditLog
        return AuditLog(str(p)).summary()
    except Exception as e:
        return {"available": False, "error": str(e)}


def _metrics_snapshot() -> dict:
    try:
        from kotak_bot.utils import metrics as M
        return M.snapshot()
    except Exception as e:
        return {"error": str(e)}


def _circuit_breakers_snapshot() -> dict:
    try:
        from kotak_bot.utils.circuit_breaker import snapshot_all
        return snapshot_all()
    except Exception as e:
        return {"error": str(e)}


# ---- request handler -------------------------------------------------------

class KotakHTTPHandler(BaseHTTPRequestHandler):
    """Routes /health, /metrics, /status."""

    # Override to suppress default access-log (too noisy in production);
    # set LOG_REQUESTS=1 to re-enable.
    LOG_REQUESTS = bool(int(os.environ.get("KOTAK_HTTP_LOG", "0")))

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 — stdlib signature
        if self.LOG_REQUESTS:
            super().log_message(format, *args)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, default=str, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, status: int, body: str, content_type: str = "text/plain; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 — stdlib signature
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/health":
            self._health()
        elif path == "/metrics":
            self._metrics()
        elif path == "/status":
            self._status()
        elif path == "/" or path == "/index.html":
            self._root()
        else:
            self._send_json(404, {"error": "not_found", "path": path,
                                  "endpoints": ["/health", "/metrics", "/status"]})

    # ---- endpoints ----

    def _root(self) -> None:
        body = (
            "Kotak Neo Bot — production HTTP server\n"
            "Endpoints:\n"
            "  /health   — liveness probe (200 ok / 503 degraded)\n"
            "  /metrics  — Prometheus text format\n"
            "  /status   — detailed JSON snapshot\n"
        )
        self._send_text(200, body)

    def _health(self) -> None:
        live = _read_liveness()
        ok = (
            live.get("available", False)
            and live.get("state") == "running"
            and live.get("age_sec", 9999) < 180
            and not (live.get("snapshot", {}) or {}).get("provider_error")
        )
        payload = {
            "ok": ok,
            "ts": datetime.now(timezone.utc).isoformat(),
            "liveness": live,
        }
        self._send_json(200 if ok else 503, payload)

    def _metrics(self) -> None:
        try:
            from kotak_bot.utils import metrics as M
            text = M.to_prometheus_text()
        except Exception as e:
            self._send_text(500, f"# error rendering metrics: {e}\n")
            return
        self._send_text(200, text, content_type="text/plain; version=0.0.4; charset=utf-8")

    def _status(self) -> None:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "liveness": _read_liveness(),
            "paper_state": _read_paper_state(),
            "audit": _read_audit_summary(),
            "metrics": _metrics_snapshot(),
            "circuit_breakers": _circuit_breakers_snapshot(),
        }
        self._send_json(200, payload)


# ---- entrypoint ------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0", help="bind address (default 0.0.0.0)")
    p.add_argument("--port", type=int, default=8502, help="port (default 8502)")
    p.add_argument("--log", action="store_true", help="log every request")
    args = p.parse_args()

    if args.log:
        KotakHTTPHandler.LOG_REQUESTS = True

    server = ThreadingHTTPServer((args.host, args.port), KotakHTTPHandler)
    print(f"[http] listening on {args.host}:{args.port}", flush=True)
    print(f"[http] endpoints: /health, /metrics, /status", flush=True)

    # Run until KeyboardInterrupt (graceful exit on Ctrl+C)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[http] shutting down...", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
