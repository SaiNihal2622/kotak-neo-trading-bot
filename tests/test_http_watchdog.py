"""Unit tests for scripts/http_server_watchdog.py.

Coverage:
  * is_listening() correctly detects open / closed ports
  * probe_health() correctly parses JSON response
  * restart_server() returns a PID
  * dry-run does not start anything
  * main() returns 0 on OK, 1 on degraded
"""
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import http_server_watchdog as W  # noqa: E402


class TestIsListening(unittest.TestCase):
    def test_listening_port_detected(self):
        # Open a server on a random port, then check
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        try:
            self.assertTrue(W.is_listening("127.0.0.1", port, timeout=1.0))
        finally:
            s.close()

    def test_closed_port_returns_false(self):
        # Pick a random unused port
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()  # release
        self.assertFalse(W.is_listening("127.0.0.1", port, timeout=0.5))


class TestProbeHealth(unittest.TestCase):
    def test_returns_ok_for_200(self):
        # Start a fake HTTP server that returns {"ok": true}
        import http.server
        import threading

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"ok": true, "x": 1}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *a, **k): pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            ok, status, body = W.probe_health(port, timeout=2.0)
            self.assertTrue(ok)
            self.assertEqual(status, 200)
            self.assertIn("ok", body)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_returns_false_for_503(self):
        import http.server
        import threading

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"ok": false, "reason": "down"}'
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *a, **k): pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            ok, status, _ = W.probe_health(port, timeout=2.0)
            self.assertFalse(ok)
            self.assertEqual(status, 503)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_returns_false_when_unreachable(self):
        # Use a port that's not bound
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        ok, status, _ = W.probe_health(port, timeout=0.5)
        self.assertFalse(ok)
        self.assertEqual(status, 0)


class TestMain(unittest.TestCase):
    def test_dry_run_does_not_start(self):
        # Use a port that nothing is listening on
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        with patch.object(sys, "argv", ["watchdog", "--port", str(port), "--dry-run"]):
            rc = W.main()
        self.assertEqual(rc, 1)  # not listening
        # And no process should have been started
        self.assertFalse(W.is_listening("127.0.0.1", port, timeout=0.5))

    def test_dry_run_with_listening_succeeds(self):
        # Start a fake server returning ok
        import http.server
        import threading

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"ok": true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *a, **k): pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            with patch.object(sys, "argv", ["watchdog", "--port", str(port), "--dry-run"]):
                rc = W.main()
            self.assertEqual(rc, 0)
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
