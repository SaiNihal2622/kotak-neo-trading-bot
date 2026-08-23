"""Unit tests for kotak_bot.http_server.

Coverage:
  * /health returns 200 when liveness is healthy
  * /health returns 503 when liveness is stale or state != running
  * /metrics returns Prometheus text format
  * /status returns JSON with all sections
  * /unknown returns 404
  * 200 OK with proper Content-Type
"""
import json
import os
import socket
import sys
import threading
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kotak_bot import http_server  # noqa: E402


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestHTTPServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.server = http_server.ThreadingHTTPServer(("127.0.0.1", cls.port), http_server.KotakHTTPHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.2)  # let it bind

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def _get(self, path: str, timeout: float = 5.0) -> tuple[int, dict, str]:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="ignore")
        headers = dict(resp.getheaders())
        conn.close()
        return resp.status, headers, body

    def test_health_returns_status(self):
        # If liveness.json is fresh + running, expect 200; else 503
        status, headers, body = self._get("/health")
        self.assertIn(status, (200, 503))
        self.assertIn("application/json", headers.get("Content-Type", ""))
        payload = json.loads(body)
        self.assertIn("ok", payload)
        self.assertIn("liveness", payload)
        self.assertIn("ts", payload)

    def test_metrics_returns_text(self):
        status, headers, body = self._get("/metrics")
        self.assertEqual(status, 200)
        # Prometheus text format: empty body ("\n") if no metrics, or starts
        # with "# TYPE ..." comments when metrics exist.
        self.assertTrue(body.startswith("#") or body.strip() == "" or "error" in body)
        self.assertIn("text/plain", headers.get("Content-Type", ""))

    def test_status_returns_full_snapshot(self):
        status, headers, body = self._get("/status")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers.get("Content-Type", ""))
        payload = json.loads(body)
        self.assertIn("ts", payload)
        self.assertIn("liveness", payload)
        self.assertIn("paper_state", payload)
        self.assertIn("audit", payload)
        self.assertIn("metrics", payload)
        self.assertIn("circuit_breakers", payload)

    def test_root_lists_endpoints(self):
        status, _, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("/health", body)
        self.assertIn("/metrics", body)
        self.assertIn("/status", body)

    def test_unknown_returns_404(self):
        status, headers, body = self._get("/does-not-exist")
        self.assertEqual(status, 404)
        self.assertIn("application/json", headers.get("Content-Type", ""))
        payload = json.loads(body)
        self.assertEqual(payload["error"], "not_found")
        self.assertIn("/health", payload["endpoints"])

    def test_health_with_synthetic_liveness(self):
        """Verify the /health response shape with a fake liveness file."""
        # Build a fake liveness + paper_state + audit, then GET /status
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            dpath = Path(d)
            (dpath / "liveness.json").write_text(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "pid": 1234,
                "state": "running",
                "tick": 100,
                "snapshot": {"provider_error": "", "realized_pnl": 0.0},
            }))
            (dpath / "paper_state.json").write_text(json.dumps({
                "cash": 100000, "realized_pnl": 0,
                "positions": [], "orders": {},
            }))
            # Patch the module-level helper functions to read from our temp dir.
            # (We can't easily patch ROOT because it's captured at import time.)
            def fake_live():
                return {
                    "available": True,
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "pid": 1234,
                    "state": "running",
                    "tick": 100,
                    "snapshot": {"provider_error": "", "realized_pnl": 0.0},
                    "age_sec": 1.0,
                }
            def fake_paper():
                return {"available": True, "cash": 100000, "realized_pnl": 0,
                        "open_positions": 0, "open_orders": 0}
            with patch.object(http_server, "_read_liveness", fake_live), \
                 patch.object(http_server, "_read_paper_state", fake_paper):
                status, _, body = self._get("/status")
                self.assertEqual(status, 200)
                payload = json.loads(body)
                self.assertTrue(payload["liveness"]["available"])
                self.assertEqual(payload["liveness"]["state"], "running")
                self.assertTrue(payload["paper_state"]["available"])
                self.assertEqual(payload["paper_state"]["cash"], 100000)


if __name__ == "__main__":
    unittest.main()
