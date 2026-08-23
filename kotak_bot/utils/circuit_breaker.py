"""Production-grade circuit breaker for risky external dependencies.

Why this exists
---------------
The bot talks to a handful of external systems that can fail in non-obvious
ways — Kotak Neo API, dashboard HTTP, Telegram, the option-chain CSV cache.
Naive retry loops can hammer a sick dependency into a deeper hole and amplify
the blast radius (e.g. exhausting the API rate limit budget for the whole day).

A circuit breaker solves this with three states:

  CLOSED      — calls flow through normally
  OPEN        — calls fail-fast without touching the dependency
                (after N consecutive failures or error-rate breach)
  HALF_OPEN   — after a cooldown, allow ONE probe call; if it succeeds, return
                to CLOSED; if it fails, return to OPEN with a fresh cooldown

Public API
----------
  CircuitBreaker(name, fail_threshold=5, error_rate_threshold=0.5,
                 cooldown_sec=60, half_open_max_concurrent=1, window_sec=300)
      .call(fn, *args, **kwargs)    → result or raises CircuitOpenError
      .state                        → "closed" | "open" | "half_open"
      .snapshot()                   → dict for metrics
      .reset()                      → force back to CLOSED

  CircuitOpenError — raised when the breaker is OPEN (does NOT call fn).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Optional


class CircuitOpenError(RuntimeError):
    """Raised by CircuitBreaker.call when the breaker is OPEN."""

    def __init__(self, breaker_name: str, retry_after_sec: float, reason: str = ""):
        super().__init__(f"circuit '{breaker_name}' is OPEN (retry after {retry_after_sec:.1f}s): {reason}")
        self.breaker_name = breaker_name
        self.retry_after_sec = retry_after_sec
        self.reason = reason


class CircuitBreaker:
    """Thread-safe circuit breaker for one external dependency."""

    def __init__(
        self,
        name: str,
        fail_threshold: int = 5,
        error_rate_threshold: float = 0.5,
        cooldown_sec: float = 60.0,
        half_open_max_concurrent: int = 1,
        window_sec: float = 300.0,
    ) -> None:
        self.name = name
        self.fail_threshold = fail_threshold
        self.error_rate_threshold = error_rate_threshold
        self.cooldown_sec = cooldown_sec
        self.half_open_max_concurrent = half_open_max_concurrent
        self.window_sec = window_sec
        self._lock = threading.Lock()
        self._state = "closed"
        self._opened_at: Optional[float] = None
        self._half_open_in_flight = 0
        # Sliding window of (ts, success_bool) pairs
        self._history: Deque[tuple[float, bool]] = deque()

    # ----------------- public API -----------------

    @property
    def state(self) -> str:
        with self._lock:
            self._maybe_close()
            return self._state

    def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Call fn through the breaker. Raises CircuitOpenError if OPEN."""
        with self._lock:
            self._maybe_close()
            if self._state == "open":
                retry_after = self._retry_after_locked()
                raise CircuitOpenError(self.name, retry_after, reason="state=open")
            if self._state == "half_open":
                if self._half_open_in_flight >= self.half_open_max_concurrent:
                    raise CircuitOpenError(self.name, 0.0, reason="half_open busy")
                self._half_open_in_flight += 1
        # Outside the lock: actually call the function
        try:
            result = fn(*args, **kwargs)
        except BaseException as e:
            self._record_failure(e)
            raise
        else:
            self._record_success()
            return result

    def snapshot(self) -> dict:
        with self._lock:
            self._maybe_close()
            now = time.time()
            cutoff = now - self.window_sec
            recent = [(t, ok) for t, ok in self._history if t >= cutoff]
            n_total = len(recent)
            n_fail = sum(1 for _, ok in recent if not ok)
            n_ok = n_total - n_fail
            err_rate = (n_fail / n_total) if n_total else 0.0
            return {
                "name": self.name,
                "state": self._state,
                "window_sec": self.window_sec,
                "n_calls": n_total,
                "n_fail": n_fail,
                "n_ok": n_ok,
                "error_rate": round(err_rate, 3),
                "opened_at": self._opened_at,
                "retry_after_sec": self._retry_after_locked() if self._state == "open" else 0.0,
            }

    def reset(self) -> None:
        """Force the breaker back to CLOSED (test/manual recovery)."""
        with self._lock:
            self._state = "closed"
            self._opened_at = None
            self._half_open_in_flight = 0
            self._history.clear()

    # ----------------- internals -----------------

    def _record_success(self) -> None:
        with self._lock:
            now = time.time()
            self._history.append((now, True))
            self._trim_locked(now)
            if self._state == "half_open":
                # Probe succeeded → close the breaker
                self._state = "closed"
                self._opened_at = None
                self._half_open_in_flight = 0
            # If closed, success just keeps the rate down

    def _record_failure(self, exc: BaseException) -> None:
        with self._lock:
            now = time.time()
            self._history.append((now, False))
            self._trim_locked(now)
            if self._state == "half_open":
                # Probe failed → re-open with fresh cooldown
                self._state = "open"
                self._opened_at = now
                self._half_open_in_flight = 0
                return
            if self._state == "closed":
                # Trip if EITHER consecutive-fail OR error-rate threshold breached
                consec_fail = self._consecutive_failures_locked()
                if consec_fail >= self.fail_threshold:
                    self._open_locked(now, reason=f"consec_fail={consec_fail}")
                    return
                err_rate = self._error_rate_locked(now)
                if (len(self._history) >= self.fail_threshold
                        and err_rate >= self.error_rate_threshold):
                    self._open_locked(now, reason=f"error_rate={err_rate:.2f}")

    def _open_locked(self, now: float, reason: str) -> None:
        self._state = "open"
        self._opened_at = now
        # Keep history so we can see the recent failures on snapshot()

    def _maybe_close(self) -> None:
        """If we're OPEN and the cooldown elapsed, transition to HALF_OPEN."""
        if self._state != "open" or self._opened_at is None:
            return
        if (time.time() - self._opened_at) >= self.cooldown_sec:
            self._state = "half_open"
            self._half_open_in_flight = 0

    def _retry_after_locked(self) -> float:
        if self._state != "open" or self._opened_at is None:
            return 0.0
        return max(0.0, self.cooldown_sec - (time.time() - self._opened_at))

    def _trim_locked(self, now: float) -> None:
        cutoff = now - self.window_sec
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()

    def _consecutive_failures_locked(self) -> int:
        n = 0
        for _, ok in reversed(self._history):
            if ok:
                break
            n += 1
        return n

    def _error_rate_locked(self, now: float) -> float:
        self._trim_locked(now)
        if not self._history:
            return 0.0
        n_fail = sum(1 for _, ok in self._history if not ok)
        return n_fail / len(self._history)


# ---- a tiny registry so callers can share breakers by name -----------------

_REGISTRY: dict[str, CircuitBreaker] = {}
_REGISTRY_LOCK = threading.Lock()


def get_or_create(
    name: str,
    **kwargs: Any,
) -> CircuitBreaker:
    """Return a singleton CircuitBreaker for ``name`` (create on first call)."""
    with _REGISTRY_LOCK:
        cb = _REGISTRY.get(name)
        if cb is None:
            cb = CircuitBreaker(name=name, **kwargs)
            _REGISTRY[name] = cb
        return cb


def snapshot_all() -> dict[str, dict]:
    """Return {name: snapshot()} for every registered breaker (for metrics)."""
    with _REGISTRY_LOCK:
        names = list(_REGISTRY.keys())
    return {n: _REGISTRY[n].snapshot() for n in names}


def reset_all() -> None:
    with _REGISTRY_LOCK:
        for cb in _REGISTRY.values():
            cb.reset()
