"""Production-grade graceful shutdown for the trading bot.

Why this exists
---------------
A trading bot that dies ungracefully can leave open positions, partial fills,
or in-flight orders whose state is unknown. Production systems always:

  1. Catch SIGTERM/SIGINT/SIGBREAK
  2. Flip a "draining" flag the main loop checks before opening new positions
  3. Optionally close open positions (if configured)
  4. Wait for the current tick to finish
  5. Flush logs and persistence
  6. Exit cleanly (rc=0)

This module is a process-wide singleton, similar to ``liveness``. Components
subscribe callbacks that run during drain, in REVERSE order of registration
(like atexit / Go defer stack).

Public API
----------
  GracefulShutdown(name, drain_timeout_sec=30)
      .is_draining()                  → bool
      .register_drain_callback(fn)    → unregister handle
      .request_shutdown(reason)       → trigger drain (sync or async)
      .wait_for_drain()               → block until done
      .install_signal_handlers()      → install SIGTERM/SIGINT/SIGBREAK handlers
      .run_with_shutdown(main_fn)     → run main_fn in a thread, signal handlers
                                        in main thread; on signal, request
                                        shutdown and wait for main_fn to return
"""
from __future__ import annotations

import logging
import signal
import sys
import threading
import time
import traceback
from typing import Callable, Optional

log = logging.getLogger("kotak_bot.shutdown")


class GracefulShutdown:
    """Process-wide graceful-shutdown coordinator."""

    def __init__(self, name: str = "kotak_bot", drain_timeout_sec: float = 30.0) -> None:
        self.name = name
        self.drain_timeout_sec = drain_timeout_sec
        self._draining = False
        self._drained = threading.Event()
        self._reason: Optional[str] = None
        self._lock = threading.Lock()
        self._callbacks: list[tuple[str, Callable[[str], None]]] = []
        self._signal_handlers_installed = False

    # ----------------- public API -----------------

    def is_draining(self) -> bool:
        return self._draining

    def register_drain_callback(
        self, fn: Callable[[str], None], name: str = "",
    ) -> Callable[[], None]:
        """Register a callback to run during drain. Returns an unregister function."""
        with self._lock:
            entry = (name or getattr(fn, "__qualname__", str(fn)), fn)
            self._callbacks.append(entry)

        def unregister() -> None:
            with self._lock:
                try:
                    self._callbacks.remove(entry)
                except ValueError:
                    pass

        return unregister

    def request_shutdown(self, reason: str = "external") -> None:
        """Trigger the drain sequence. Idempotent."""
        with self._lock:
            if self._draining:
                return
            self._draining = True
            self._reason = reason
        log.info("[shutdown] drain requested (reason=%s)", reason)
        t0 = time.perf_counter()
        # Run callbacks in REVERSE registration order (LIFO, like a defer stack)
        with self._lock:
            callbacks = list(reversed(self._callbacks))
        for name, fn in callbacks:
            try:
                log.debug("[shutdown] running drain callback: %s", name)
                fn(self._reason or reason)
            except Exception as e:
                log.error(
                    "[shutdown] drain callback %s raised: %s\n%s",
                    name, e, traceback.format_exc(limit=5),
                )
        self._drained.set()
        log.info(
            "[shutdown] drain complete (reason=%s, took %.2fs)",
            reason, time.perf_counter() - t0,
        )

    def wait_for_drain(self, timeout: Optional[float] = None) -> bool:
        """Block until drain completes or timeout. Returns True if drained."""
        return self._drained.wait(timeout=timeout or self.drain_timeout_sec)

    def install_signal_handlers(self) -> None:
        """Install SIGTERM/SIGINT/SIGBREAK handlers that trigger drain."""
        if self._signal_handlers_installed:
            return
        for sig_name in ("SIGTERM", "SIGINT"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, self._make_signal_handler(sig_name))
            except (ValueError, OSError):
                # Not in main thread, or signal not supported on this platform
                pass
        # Windows-specific
        if hasattr(signal, "SIGBREAK"):
            try:
                signal.signal(signal.SIGBREAK, self._make_signal_handler("SIGBREAK"))
            except (ValueError, OSError):
                pass
        self._signal_handlers_installed = True

    def run_with_shutdown(self, main_fn: Callable[[], None]) -> int:
        """Run main_fn in a thread; install signal handlers in main thread.

        Returns the process exit code (0 = clean, 1 = main raised).
        """
        self.install_signal_handlers()
        main_thread = threading.Thread(target=self._safe_run_main, args=(main_fn,), daemon=True)
        main_thread.start()
        # Block here until drain is requested
        while not self._draining:
            time.sleep(0.1)
        # Wait for main_fn to finish (it should observe is_draining() and exit)
        main_thread.join(timeout=self.drain_timeout_sec)
        if main_thread.is_alive():
            log.warning("[shutdown] main thread didn't exit within %.1fs, exiting anyway", self.drain_timeout_sec)
        return 0

    # ----------------- internals -----------------

    def _make_signal_handler(self, sig_name: str):
        def handler(signum, frame):  # noqa: ARG001 — signal signature
            self.request_shutdown(reason=f"signal:{sig_name}")
        return handler

    def _safe_run_main(self, main_fn: Callable[[], None]) -> None:
        try:
            main_fn()
        except SystemExit:
            # Normal exit
            pass
        except BaseException as e:
            log.error("[shutdown] main raised: %s\n%s", e, traceback.format_exc(limit=10))
            self.request_shutdown(reason=f"main_exception:{type(e).__name__}")
            raise
        else:
            self.request_shutdown(reason="main_returned")


# ---- module-level singleton ------------------------------------------------
_DEFAULT: Optional[GracefulShutdown] = None
_DEFAULT_LOCK = threading.Lock()


def get_default() -> Optional[GracefulShutdown]:
    return _DEFAULT


def install_default(name: str = "kotak_bot", drain_timeout_sec: float = 30.0) -> GracefulShutdown:
    """Install a process-wide GracefulShutdown (singleton)."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = GracefulShutdown(name=name, drain_timeout_sec=drain_timeout_sec)
        return _DEFAULT
