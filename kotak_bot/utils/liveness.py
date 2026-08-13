"""Liveness monitor + crash reporting.

Why this exists
---------------
We have observed the bot die cleanly (exit 0) 3+ times/week with no traceback
and no FATAL log line. Hypothesis is one of: laptop sleep, Windows process
limit, parent-process kill, Kotak session expiry silent kill.

This module gives us forensic data on every exit:
  * Writes a liveness ping to a file every N seconds (default 30s).
  * If the file goes stale (> 2x interval), the external watchdog (cron) can
    detect the dead process.
  * Registers an atexit handler that logs the exit reason to a separate
    crash file BEFORE the interpreter tears down.
  * Registers signal handlers (SIGTERM, SIGINT, SIGBREAK on Windows) so we
    can log the kill cause before clean shutdown.

Public API
----------
  LivenessMonitor(ping_file, crash_file, interval_sec)
      .start()    — spawn background thread
      .stop()     — graceful stop (called by signal handlers / atexit)
      .ping()     — manual one-shot ping (rarely needed)
      .is_alive() — quick check (last ping age in seconds)
      .register_exit(reason: str)  — call before clean shutdown to log exit cause

Crash file format (JSONL, one event per line):
  {"ts": "2026-08-13T18:55:00.123+05:30",
   "event": "exit" | "signal" | "crash" | "stop",
   "reason": "...",
   "uptime_sec": 12345.6,
   "last_ping_age_sec": 0.4,
   "main_thread_alive": true,
   "python_version": "3.11.9",
   "pid": 12345,
   "ppid": 67890,
   "extra": {...}}

Liveness file format (JSON, rewritten every interval):
  {"ts": "...", "pid": 12345, "uptime_sec": 12.3, "tick": 42, "state": "running"}
"""
from __future__ import annotations

import atexit
import json
import os
import platform
import signal
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


def _now_iso() -> str:
    """Return current time in ISO 8601 with timezone (local)."""
    return datetime.now().astimezone().isoformat()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LivenessMonitor:
    """Background-thread liveness + crash-reporting for the trading bot."""

    def __init__(
        self,
        ping_file: str = "data_cache/liveness.json",
        crash_file: str = "data_cache/liveness_crash.jsonl",
        interval_sec: float = 30.0,
        state_provider: Optional[Callable[[], dict]] = None,
    ) -> None:
        self.ping_file = Path(ping_file)
        self.crash_file = Path(crash_file)
        # Enforce a sane minimum of 1.0s — anything lower is just busy-looping
        # the disk and will burn through SDD/SSD write cycles for no benefit
        self.interval_sec = max(1.0, float(interval_sec))
        self.state_provider = state_provider
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started_at = time.time()
        self._tick_count = 0
        self._last_ping_ts: Optional[float] = None
        self._registered_atexit = False
        self._registered_signals = False
        self._lock = threading.Lock()
        # Make sure parents exist
        self.ping_file.parent.mkdir(parents=True, exist_ok=True)
        self.crash_file.parent.mkdir(parents=True, exist_ok=True)

    # ----------------- public API -----------------

    def start(self) -> None:
        """Start the liveness background thread + register exit/signal hooks.

        Idempotent — calling twice is a no-op.
        """
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            # Register atexit first (runs even on unhandled exception, before
            # interpreter teardown)
            if not self._registered_atexit:
                atexit.register(self._on_atexit)
                self._registered_atexit = True
            # Register signal handlers (best-effort on Windows)
            if not self._registered_signals:
                self._register_signal_handlers()
                self._registered_signals = True
            # First ping immediately so watchdog has data even if we die early
            self._ping_now(state="starting")
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="liveness-monitor",
                daemon=True,
            )
            self._thread.start()

    def stop(self, reason: str = "graceful") -> None:
        """Stop the liveness thread and write a final exit event."""
        with self._lock:
            self._stop_event.set()
            t = self._thread
        if t and t.is_alive():
            t.join(timeout=self.interval_sec * 2)
        # Final exit event (atexit will also fire and may double-log; that's OK
        # because the JSONL file accepts multiple events)
        self._write_crash(event="stop", reason=reason)

    def ping(self) -> None:
        """Manual one-shot ping (rarely needed; the thread does this)."""
        self._ping_now(state="manual")

    def is_alive(self, max_age_sec: Optional[float] = None) -> bool:
        """True if the most recent ping is fresher than max_age_sec (default 2× interval)."""
        if self._last_ping_ts is None:
            return False
        if max_age_sec is None:
            max_age_sec = self.interval_sec * 2
        return (time.time() - self._last_ping_ts) <= max_age_sec

    def last_ping_age_sec(self) -> Optional[float]:
        if self._last_ping_ts is None:
            return None
        return time.time() - self._last_ping_ts

    def register_exit(self, reason: str, extra: Optional[dict] = None) -> None:
        """Synchronously write a custom exit event (call before sys.exit / clean shutdown)."""
        self._write_crash(event="exit", reason=reason, extra=extra)

    # ----------------- internal -----------------

    def _run(self) -> None:
        # Sleep FIRST so the "starting" ping written by start() stays visible
        # for a window (useful for tests + external watchers)
        if self._stop_event.wait(timeout=self.interval_sec):
            return  # stop requested during initial sleep
        while not self._stop_event.is_set():
            try:
                self._ping_now(state="running")
            except Exception as e:
                # Never let the liveness thread itself die
                try:
                    self._write_crash(
                        event="crash",
                        reason=f"liveness_ping_failed: {e}",
                        extra={"traceback": traceback.format_exc(limit=5)},
                    )
                except Exception:
                    pass
            # Sleep in small chunks so stop() is responsive
            slept = 0.0
            while slept < self.interval_sec and not self._stop_event.is_set():
                time.sleep(min(0.5, self.interval_sec - slept))
                slept += 0.5

    def _ping_now(self, state: str) -> None:
        now = time.time()
        state_data: dict[str, Any] = {}
        if self.state_provider is not None:
            try:
                state_data = self.state_provider() or {}
            except Exception as e:
                state_data = {"provider_error": str(e)}
        payload = {
            "ts": _now_iso(),
            "pid": os.getpid(),
            "uptime_sec": round(now - self._started_at, 2),
            "tick": self._tick_count,
            "state": state,
            "main_thread_alive": threading.main_thread().is_alive(),
        }
        if state_data:
            payload["snapshot"] = state_data
        tmp = self.ping_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, default=str), encoding="utf-8")
        # Atomic-ish rename
        try:
            os.replace(tmp, self.ping_file)
        except OSError:
            # Fallback for Windows if rename races
            self.ping_file.write_text(json.dumps(payload, default=str), encoding="utf-8")
        self._tick_count += 1
        self._last_ping_ts = now

    def _write_crash(
        self,
        event: str,
        reason: str,
        extra: Optional[dict] = None,
    ) -> None:
        try:
            now = time.time()
            payload = {
                "ts": _now_iso(),
                "event": event,
                "reason": reason,
                "uptime_sec": round(now - self._started_at, 2),
                "last_ping_age_sec": (
                    round(now - self._last_ping_ts, 2) if self._last_ping_ts else None
                ),
                "main_thread_alive": (
                    threading.main_thread().is_alive() if threading.main_thread().is_alive() is not None else None
                ),
                "python_version": platform.python_version(),
                "pid": os.getpid(),
                "ppid": os.getppid() if hasattr(os, "getppid") else None,
                "platform": platform.platform(),
            }
            if extra:
                payload["extra"] = extra
            with self.crash_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, default=str) + "\n")
        except Exception:
            # Last-ditch: never let logging the crash itself crash
            pass

    def _on_atexit(self) -> None:
        """atexit hook — runs once on interpreter shutdown, whatever the cause."""
        # We can't always tell why we're shutting down, but we can record state.
        # If a signal handler set _exit_reason, prefer that.
        reason = getattr(self, "_exit_reason", None) or "atexit_normal"
        self._write_crash(event="atexit", reason=reason)
        # Best-effort: stop the thread (atexit doesn't wait for daemon threads,
        # but stopping is cheap and idempotent)
        self._stop_event.set()

    def _register_signal_handlers(self) -> None:
        """Best-effort signal handler registration. SIGBREAK only on Windows."""
        for sig_name in ("SIGTERM", "SIGINT"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, self._make_signal_handler(sig_name))
            except (ValueError, OSError):
                # Not in main thread, or signal not supported on this platform
                pass
        # Windows-specific Ctrl+Break (sent by `nssm stop` and Ctrl+Break in console)
        if hasattr(signal, "SIGBREAK"):
            try:
                signal.signal(signal.SIGBREAK, self._make_signal_handler("SIGBREAK"))
            except (ValueError, OSError):
                pass

    def _make_signal_handler(self, sig_name: str):
        def handler(signum, frame):  # noqa: ARG001 — signal handler signature
            self._exit_reason = f"signal:{sig_name}"
            self._write_crash(event="signal", reason=sig_name)
            # Re-raise default behavior (so the process actually exits)
            # by calling the previous handler if registered
            try:
                # For SIGINT this re-raises KeyboardInterrupt on next call site.
                # Simpler: just exit cleanly here.
                sys.exit(0)
            except SystemExit:
                raise
        return handler


# ----------------- module-level singleton -----------------
_DEFAULT: Optional[LivenessMonitor] = None
_DEFAULT_LOCK = threading.Lock()


def get_default() -> Optional[LivenessMonitor]:
    return _DEFAULT


def install_default(
    ping_file: str = "data_cache/liveness.json",
    crash_file: str = "data_cache/liveness_crash.jsonl",
    interval_sec: float = 30.0,
    state_provider: Optional[Callable[[], dict]] = None,
) -> LivenessMonitor:
    """Install a process-wide liveness monitor (singleton)."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = LivenessMonitor(
                ping_file=ping_file,
                crash_file=crash_file,
                interval_sec=interval_sec,
                state_provider=state_provider,
            )
        return _DEFAULT
