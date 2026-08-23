"""Unit tests for kotak_bot.utils.circuit_breaker.

Coverage:
  * Closed → Open transition on consecutive failures
  * Closed → Open transition on error-rate threshold
  * Open → Half-open after cooldown
  * Half-open success → Closed
  * Half-open failure → Open (with fresh cooldown)
  * CircuitOpenError raised when open (no fn call)
  * Snapshot exposes current state
  * Registry returns singleton per name
"""
import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kotak_bot.utils.circuit_breaker import (  # noqa: E402
    CircuitBreaker, CircuitOpenError, get_or_create, reset_all, snapshot_all,
)


class TestCircuitBreaker(unittest.TestCase):

    def setUp(self):
        reset_all()

    def test_closed_passes_calls_through(self):
        cb = CircuitBreaker("test", fail_threshold=3, cooldown_sec=0.1)
        self.assertEqual(cb.state, "closed")
        self.assertEqual(cb.call(lambda: 42), 42)
        self.assertEqual(cb.state, "closed")

    def test_opens_on_consecutive_failures(self):
        cb = CircuitBreaker("test", fail_threshold=3, cooldown_sec=10.0, error_rate_threshold=1.0)
        for _ in range(3):
            with self.assertRaises(RuntimeError):
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        self.assertEqual(cb.state, "open")
        with self.assertRaises(CircuitOpenError):
            cb.call(lambda: "should not run")

    def test_opens_on_error_rate_threshold(self):
        cb = CircuitBreaker("test", fail_threshold=10, cooldown_sec=10.0,
                            error_rate_threshold=0.5, window_sec=60.0)
        # 4 successes, 6 failures → 60% error rate → should open
        for _ in range(4):
            self.assertEqual(cb.call(lambda: "ok"), "ok")
        for _ in range(6):
            with self.assertRaises(RuntimeError):
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        self.assertEqual(cb.state, "open")

    def test_open_transitions_to_half_open_after_cooldown(self):
        cb = CircuitBreaker("test", fail_threshold=2, cooldown_sec=0.1)
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        self.assertEqual(cb.state, "open")
        time.sleep(0.15)  # let cooldown elapse
        # next call should be allowed (half-open probe)
        self.assertEqual(cb.call(lambda: "probe-ok"), "probe-ok")
        self.assertEqual(cb.state, "closed")

    def test_half_open_failure_reopens_with_fresh_cooldown(self):
        cb = CircuitBreaker("test", fail_threshold=2, cooldown_sec=0.1)
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        time.sleep(0.15)
        # probe fails → re-open
        with self.assertRaises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        self.assertEqual(cb.state, "open")

    def test_circuit_open_error_includes_retry_after(self):
        cb = CircuitBreaker("test", fail_threshold=1, cooldown_sec=30.0)
        with self.assertRaises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        with self.assertRaises(CircuitOpenError) as cm:
            cb.call(lambda: "blocked")
        self.assertIn("retry after", str(cm.exception))
        self.assertGreater(cm.exception.retry_after_sec, 0)

    def test_snapshot_shape(self):
        cb = CircuitBreaker("test", fail_threshold=10, cooldown_sec=60.0, window_sec=120.0)
        self.assertEqual(cb.call(lambda: "ok"), "ok")
        with self.assertRaises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        snap = cb.snapshot()
        self.assertEqual(snap["name"], "test")
        self.assertEqual(snap["state"], "closed")
        self.assertEqual(snap["n_calls"], 2)
        self.assertEqual(snap["n_fail"], 1)
        self.assertEqual(snap["n_ok"], 1)
        self.assertEqual(snap["error_rate"], 0.5)

    def test_reset_clears_state(self):
        cb = CircuitBreaker("test", fail_threshold=1, cooldown_sec=99.0)
        with self.assertRaises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        self.assertEqual(cb.state, "open")
        cb.reset()
        self.assertEqual(cb.state, "closed")
        self.assertEqual(cb.call(lambda: "ok"), "ok")

    def test_consecutive_failures_reset_on_success(self):
        cb = CircuitBreaker("test", fail_threshold=3, cooldown_sec=99.0, error_rate_threshold=1.0)
        # 2 fails, 1 success, 2 more fails → should NOT open (streak reset)
        with self.assertRaises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        with self.assertRaises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        self.assertEqual(cb.call(lambda: "ok"), "ok")
        with self.assertRaises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        with self.assertRaises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        self.assertEqual(cb.state, "closed")  # streak was reset by the success


class TestRegistry(unittest.TestCase):
    def setUp(self):
        reset_all()

    def test_get_or_create_returns_singleton(self):
        a = get_or_create("kotak_api", fail_threshold=5)
        b = get_or_create("kotak_api", fail_threshold=999)  # different kwargs ignored
        self.assertIs(a, b)

    def test_snapshot_all(self):
        get_or_create("kotak_api", fail_threshold=5)
        get_or_create("telegram", fail_threshold=3)
        snap = snapshot_all()
        self.assertIn("kotak_api", snap)
        self.assertIn("telegram", snap)


if __name__ == "__main__":
    unittest.main()
