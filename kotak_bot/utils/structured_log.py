"""Production-grade structured JSON logger.

Why this exists
---------------
The default ``loguru``/stdlib logger writes human-readable lines, which are fine
for development but unsearchable and unaggregatable. For production we need:

  1. Every log line is a single-line JSON object — easy to grep / jq / load into
     a data warehouse.
  2. Each line carries the standard envelope: ``ts``, ``level``, ``logger``,
     ``msg``, ``module``, ``pid``, plus the call-site context.
  3. Per-event structured fields (``extra``) get flattened into the top-level
     JSON so they're queryable without parsing nested objects.
  4. Rotating file handler with size cap (10MB × 5 backups) so the log never
     fills the disk.
  5. Failures inside the logger itself never propagate to the caller.

Public API
----------
  configure(json_path, level, also_console)
      Set up the global JSON logger. Idempotent.

  get_logger(name)
      Return a bound logger that automatically includes ``name`` in every event.

  log_event(level, event, **fields)
      One-shot structured event (preferred for "things that happen", not
      "things that go wrong" — those should use logger.exception).

  log_call(name, fn, *args, **kwargs)
      Decorator that wraps a function call with timing + exception capture.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import sys
import threading
import time
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Optional

# ---- standard envelope ----------------------------------------------------

_RESERVED_KEYS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime",
}


class JsonFormatter(logging.Formatter):
    """Render every log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        # Build the envelope
        envelope: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created))
                  + f".{int(record.msecs):03d}",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
            "pid": record.process,
            "thread": record.threadName,
        }
        # Flatten all custom fields attached via logger.info(..., extra={...})
        for key, val in record.__dict__.items():
            if key in _RESERVED_KEYS or key.startswith("_"):
                continue
            if key in envelope:
                continue  # don't let extras clobber envelope
            envelope[key] = _safe(val)
        # Exception info → structured traceback field
        if record.exc_info:
            try:
                envelope["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
                envelope["exc"] = "".join(traceback.format_exception(*record.exc_info)).rstrip()
            except Exception:
                envelope["exc"] = "format_failed"
        try:
            return json.dumps(envelope, default=str, ensure_ascii=False)
        except Exception:
            # Last-ditch: strip to a safe minimal envelope
            return json.dumps({"ts": envelope["ts"], "level": "ERROR",
                              "logger": envelope.get("logger", "?"),
                              "msg": "log_format_failed",
                              "orig_msg": str(envelope.get("msg", ""))[:500]},
                             ensure_ascii=False)


def _safe(obj: Any) -> Any:
    """Coerce an object to something JSON-serializable."""
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_safe(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _safe(v) for k, v in obj.items()}
    if isinstance(obj, (set, frozenset)):
        return sorted(_safe(x) for x in obj)
    if isinstance(obj, Path):
        return str(obj)
    return str(obj)


# ---- module-level singleton ------------------------------------------------

_CONFIGURED = False
_CONFIGURED_LOCK = threading.Lock()


def configure(
    json_path: str = "data_cache/runtime.jsonl",
    level: str = "INFO",
    also_console: bool = True,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """Set up the global JSON logger. Idempotent — call multiple times safely."""
    global _CONFIGURED
    with _CONFIGURED_LOCK:
        if _CONFIGURED:
            return logging.getLogger("kotak_bot")
        # Make sure parent exists
        p = Path(json_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Build the root logger for our package
        root = logging.getLogger("kotak_bot")
        root.setLevel(getattr(logging, level.upper(), logging.INFO))
        # Wipe out any pre-existing handlers (e.g. from previous configure call
        # or from loguru auto-config). Idempotent.
        for h in list(root.handlers):
            root.removeHandler(h)
        # File handler — rotating JSON
        fh = RotatingFileHandler(
            str(p), maxBytes=max_bytes, backupCount=backup_count,
            encoding="utf-8", delay=True,
        )
        fh.setFormatter(JsonFormatter())
        root.addHandler(fh)
        # Console handler — only if requested (prod runs typically disable)
        if also_console:
            ch = logging.StreamHandler(stream=sys.stderr)
            ch.setFormatter(JsonFormatter())
            root.addHandler(ch)
        # Don't propagate to root (which has its own handlers)
        root.propagate = False
        # Quiet down noisy libs
        for noisy in ("urllib3", "asyncio", "httpcore"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        _CONFIGURED = True
        return root


def get_logger(name: str = "kotak_bot") -> logging.Logger:
    """Return a logger under the ``kotak_bot`` namespace."""
    if not _CONFIGURED:
        configure()
    return logging.getLogger(name)


def log_event(
    level: str,
    event: str,
    **fields: Any,
) -> None:
    """One-shot structured event.

    Example::

        log_event("INFO", "order.placed", symbol="NIFTY", side="BUY",
                  qty=75, price=125.5, order_id="OD123")

    Renders as::

        {"ts": "...", "level": "INFO", "logger": "kotak_bot",
         "msg": "order.placed", "event": "order.placed", "symbol": "NIFTY", ...}
    """
    log = get_logger()
    # 'event' is the canonical message AND a structured field (so we can
    # filter on it without parsing the msg).
    fields = {"event": event, **fields}
    getattr(log, level.lower())(event, extra=fields)


def log_call(
    name: Optional[str] = None,
    level: str = "INFO",
    reraise: bool = True,
) -> Callable:
    """Decorator: wrap a function call with timing + exception capture.

    Example::

        @log_call("risk.evaluate")
        def evaluate(state):
            ...

    On success: emits ``<name>.ok`` with ``duration_ms`` field.
    On failure: emits ``<name>.error`` with ``exc_type`` + ``exc``, then re-raises.
    """
    def deco(fn: Callable) -> Callable:
        call_name = name or f"{fn.__module__}.{fn.__qualname__}"

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
                dt = (time.perf_counter() - t0) * 1000
                log_event(level, f"{call_name}.ok", duration_ms=round(dt, 2))
                return result
            except Exception as e:
                dt = (time.perf_counter() - t0) * 1000
                log_event(
                    "ERROR", f"{call_name}.error",
                    duration_ms=round(dt, 2),
                    exc_type=type(e).__name__,
                    exc=str(e)[:1000],
                )
                if reraise:
                    raise
                return None
        return wrapper
    return deco


# ---- self-test ------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    configure(json_path="data_cache/runtime_test.jsonl", also_console=True)
    log = get_logger("kotak_bot.test")
    log.info("hello world", extra={"user": "sai", "n": 42})
    try:
        1 / 0
    except ZeroDivisionError:
        log.exception("boom")
    log_event("INFO", "order.placed", symbol="NIFTY", side="BUY", qty=75, price=125.5)
