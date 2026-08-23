"""Production-grade retry with exponential backoff + jitter.

Why this exists
---------------
Naive retry loops cause two problems in production:
  1. Thundering-herd — all retries fire at the same instant, overloading
     the upstream service that's already struggling.
  2. Cascading failure — retrying a fundamentally broken call (e.g. 401
     auth error) wastes the rate-limit budget.

This module solves both with:
  * Exponential backoff (delay = base * factor ** attempt)
  * Jitter (random ±25% of the computed delay) to spread retries
  * Max attempts cap
  * Predicate for which exceptions are retriable

Public API
----------
  retry_with_backoff(fn, *, max_attempts=3, base_sec=1.0, max_sec=30.0,
                     factor=2.0, retriable=None, on_retry=None)
      Run ``fn()`` with backoff between attempts.

  @retry decorator (same kwargs)
  RetriableError — base class for "this IS worth retrying" exceptions
  NonRetriableError — base class for "do NOT retry this" (skipped)
"""
from __future__ import annotations

import functools
import logging
import random
import time
import traceback
from typing import Any, Callable, Optional, Type, TypeVar, Union

log = logging.getLogger("kotak_bot.retry")
T = TypeVar("T")


class RetriableError(Exception):
    """Base class for exceptions that ARE worth retrying."""


class NonRetriableError(Exception):
    """Base class for exceptions that should NOT be retried (skip immediately)."""


def _is_retriable(
    exc: BaseException,
    retriable: Optional[Union[Callable[[BaseException], bool], tuple[Type[BaseException], ...]]],
) -> bool:
    if retriable is None:
        return True
    if isinstance(retriable, tuple):
        return isinstance(exc, retriable)
    try:
        return bool(retriable(exc))
    except Exception:
        return True


def _compute_delay(attempt: int, base_sec: float, max_sec: float, factor: float) -> float:
    """Exponential backoff with ±25% jitter."""
    raw = min(max_sec, base_sec * (factor ** attempt))
    # Jitter: spread retries across a 50% window
    return raw * (0.75 + random.random() * 0.5)


def retry_with_backoff(
    fn: Callable[..., T],
    *args: Any,
    max_attempts: int = 3,
    base_sec: float = 1.0,
    max_sec: float = 30.0,
    factor: float = 2.0,
    retriable: Optional[Union[Callable[[BaseException], bool], tuple[Type[BaseException], ...]]] = None,
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
    **kwargs: Any,
) -> T:
    """Run fn(*args, **kwargs) with exponential-backoff retry.

    Returns the first successful result. Raises the last exception if all
    attempts fail, or immediately raises a NonRetriableError subclass.

    Args:
        fn: the callable to invoke
        max_attempts: total tries (>=1). Default 3.
        base_sec: initial backoff delay in seconds. Default 1.0.
        max_sec: cap on any single delay. Default 30.0.
        factor: exponential growth factor (e.g. 2.0 doubles each time).
        retriable: filter — None (all), a tuple of exception types, or a
            predicate ``(exc) -> bool``.
        on_retry: optional ``(attempt_idx, exception, next_delay_sec) -> None``
            callback. Useful for logging / metrics.
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except NonRetriableError:
            # Not retriable — fail fast
            raise
        except BaseException as e:  # noqa: BLE001 — we re-raise after retries
            if not _is_retriable(e, retriable):
                raise
            last_exc = e
            if attempt == max_attempts - 1:
                # Out of attempts
                log.error(
                    "[retry] exhausted %d attempts on %s: %s",
                    max_attempts, getattr(fn, "__qualname__", str(fn)), e,
                )
                raise
            delay = _compute_delay(attempt, base_sec, max_sec, factor)
            log.warning(
                "[retry] attempt %d/%d failed (%s) — retrying in %.2fs",
                attempt + 1, max_attempts, e, delay,
            )
            if on_retry is not None:
                try:
                    on_retry(attempt, e, delay)
                except Exception:
                    pass
            time.sleep(delay)
    # Should be unreachable (the loop either returns or raises)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("retry_with_backoff: unreachable")


def retry(
    *,
    max_attempts: int = 3,
    base_sec: float = 1.0,
    max_sec: float = 30.0,
    factor: float = 2.0,
    retriable: Optional[Union[Callable[[BaseException], bool], tuple[Type[BaseException], ...]]] = None,
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator form of ``retry_with_backoff``."""
    def deco(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            return retry_with_backoff(
                fn, *args,
                max_attempts=max_attempts,
                base_sec=base_sec,
                max_sec=max_sec,
                factor=factor,
                retriable=retriable,
                on_retry=on_retry,
                **kwargs,
            )
        return wrapper
    return deco


# ---- self-test -------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)

    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError(f"flaky #{attempts['n']}")
        return "ok"

    print("With backoff:", retry_with_backoff(flaky, max_attempts=5, base_sec=0.05, max_sec=0.5))
    print(f"Total attempts: {attempts['n']}")
