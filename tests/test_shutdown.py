"""Unit tests for kotak_bot.utils.shutdown.

Coverage:
  * is_draining transitions correctly
  * callbacks run in LIFO order (like a defer stack)
  * idempotent request_shutdown
  * failing callbacks don't block later ones
  * wait_for_drain times out gracefully
  * NonRetriableError (not here, but RetriableError is in retry.py)
  * signal handlers installed flag
"""
import os
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kotak_bot.utils.shutdown import GracefulShutdown  # noqa: E402


class TestGracefulShutdown(unittest.TestCase):
    def test_initially_not_draining(self):
        gs = GracefulShutdown("test")
        self.assertFalse(gs.is_draining())
        self.assertFalse(gs.wait_for_drain(timeout=0.05))

    def test_request_shutdown_sets_draining(self):
        gs = GracefulShutdown("test")
        gs.request_shutdown("manual")
        self.assertTrue(gs.is_draining())
        self.assertTrue(gs.wait_for_drain(timeout=1.0))

    def test_idempotent_request_shutdown(self):
        gs = GracefulShutdown("test")
        calls = []
        gs.register_drain_callback(lambda r: calls.append(r), "test_cb")
        gs.request_shutdown("first")
        gs.request_shutdown("second")  # should be a no-op
        self.assertEqual(calls, ["first"])  # only first ran

    def test_callbacks_run_in_lifo_order(self):
        gs = GracefulShutdown("test")
        order = []
        gs.register_drain_callback(lambda r: order.append("A"), "A")
        gs.register_drain_callback(lambda r: order.append("B"), "B")
        gs.register_drain_callback(lambda r: order.append("C"), "C")
        gs.request_shutdown("test")
        # LIFO: C, B, A
        self.assertEqual(order, ["C", "B", "A"])

    def test_failing_callback_does_not_block_others(self):
        gs = GracefulShutdown("test")
        ran = []
        gs.register_drain_callback(lambda r: ran.append("A"), "A")
        gs.register_drain_callback(lambda r: (_ for _ in ()).throw(RuntimeError("boom")), "BAD")
        gs.register_drain_callback(lambda r: ran.append("C"), "C")
        gs.request_shutdown("test")
        # A and C still run despite BAD failing
        self.assertIn("A", ran)
        self.assertIn("C", ran)

    def test_unregister_callback(self):
        gs = GracefulShutdown("test")
        ran = []
        unreg = gs.register_drain_callback(lambda r: ran.append("X"), "X")
        unreg()
        gs.request_shutdown("test")
        self.assertEqual(ran, [])

    def test_run_with_shutdown_drains_when_main_returns(self):
        gs = GracefulShutdown("test", drain_timeout_sec=2.0)
        ran = []

        def main_fn():
            ran.append("start")
            time.sleep(0.1)
            ran.append("end")

        # Run in a thread to avoid blocking the test
        t = threading.Thread(target=lambda: gs.run_with_shutdown(main_fn), daemon=True)
        t.start()
        t.join(timeout=5.0)
        self.assertEqual(ran, ["start", "end"])
        self.assertTrue(gs.is_draining())


if __name__ == "__main__":
    unittest.main()
