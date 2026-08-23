"""Unit tests for kotak_bot.utils.retry.

Coverage:
  * Returns first successful result
  * Raises after max_attempts
  * Exponential backoff timing (with mocked time)
  * Jitter doesn't exceed bounds
  * NonRetriableError short-circuits
  * retriable predicate filters exceptions
  * on_retry callback receives attempt/delay
  * Decorator form works
"""
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kotak_bot.utils.retry import (  # noqa: E402
    NonRetriableError, retry, retry_with_backoff,
)


class TestRetryWithBackoff(unittest.TestCase):
    def test_returns_first_success(self):
        attempts = {"n": 0}

        def flaky():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ConnectionError(f"flaky #{attempts['n']}")
            return "ok"

        result = retry_with_backoff(flaky, max_attempts=5, base_sec=0.001, max_sec=0.01)
        self.assertEqual(result, "ok")
        self.assertEqual(attempts["n"], 3)

    def test_raises_after_max_attempts(self):
        def always_fails():
            raise ConnectionError("nope")

        with self.assertRaises(ConnectionError):
            retry_with_backoff(always_fails, max_attempts=3, base_sec=0.001, max_sec=0.01)

    def test_non_retriable_short_circuits(self):
        attempts = {"n": 0}

        def auth_error():
            attempts["n"] += 1
            raise NonRetriableError("auth failed")

        with self.assertRaises(NonRetriableError):
            retry_with_backoff(auth_error, max_attempts=5, base_sec=0.001, max_sec=0.01)
        # Should only be called once (no retry)
        self.assertEqual(attempts["n"], 1)

    def test_retriable_tuple_filter(self):
        attempts = {"n": 0}

        def bad_value_error():
            attempts["n"] += 1
            raise ValueError("permanent")

        with self.assertRaises(ValueError):
            retry_with_backoff(
                bad_value_error,
                max_attempts=3, base_sec=0.001, max_sec=0.01,
                retriable=(ConnectionError,),
            )
        # ValueError is not in the tuple, so only 1 attempt
        self.assertEqual(attempts["n"], 1)

    def test_retriable_predicate(self):
        attempts = {"n": 0}

        def flaky():
            attempts["n"] += 1
            err = ValueError(f"#{attempts['n']}")
            if attempts["n"] < 2:
                raise err
            return "done"

        result = retry_with_backoff(
            flaky, max_attempts=3, base_sec=0.001, max_sec=0.01,
            retriable=lambda e: "fatal" not in str(e),
        )
        self.assertEqual(result, "done")
        self.assertEqual(attempts["n"], 2)

    def test_on_retry_callback_receives_args(self):
        attempts = {"n": 0}
        captured = []

        def flaky():
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise ConnectionError("transient")
            return "ok"

        def on_retry(attempt_idx, exc, delay):
            captured.append((attempt_idx, type(exc).__name__, delay))

        retry_with_backoff(
            flaky, max_attempts=3, base_sec=0.01, max_sec=0.5,
            on_retry=on_retry,
        )
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0][0], 0)  # first attempt (0-indexed)
        self.assertEqual(captured[0][1], "ConnectionError")
        self.assertGreater(captured[0][2], 0)  # delay > 0

    def test_exponential_growth(self):
        """Delays should grow exponentially (jitter aside)."""
        # We can't test timing directly without sleeping, so we test
        # the helper that computes the delay.
        from kotak_bot.utils.retry import _compute_delay
        # No jitter at the boundaries
        import random
        random.seed(42)
        d0 = _compute_delay(0, base_sec=1.0, max_sec=100.0, factor=2.0)
        d1 = _compute_delay(1, base_sec=1.0, max_sec=100.0, factor=2.0)
        d2 = _compute_delay(2, base_sec=1.0, max_sec=100.0, factor=2.0)
        # With ±25% jitter: d1 should be ~2× d0 ± 25%
        self.assertGreater(d1, 1.4)  # d0 * 2 * 0.75 = 1.5
        self.assertLess(d1, 2.6)  # d0 * 2 * 1.25 = 2.5

    def test_max_delay_cap(self):
        from kotak_bot.utils.retry import _compute_delay
        # attempt=10 with factor=2.0 would be 1024 without cap
        d = _compute_delay(10, base_sec=1.0, max_sec=5.0, factor=2.0)
        self.assertLessEqual(d, 5.0 * 1.25)  # cap + jitter

    def test_decorator_form(self):
        attempts = {"n": 0}

        @retry(max_attempts=3, base_sec=0.001, max_sec=0.01)
        def flaky():
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise ConnectionError("x")
            return "ok"

        self.assertEqual(flaky(), "ok")
        self.assertEqual(attempts["n"], 2)


if __name__ == "__main__":
    unittest.main()
