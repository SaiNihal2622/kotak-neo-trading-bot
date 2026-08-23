"""Unit tests for kotak_bot.utils.structured_log.

Coverage:
  * JSON envelope shape is correct
  * Extra fields are flattened (not nested)
  * Exceptions are captured as structured traceback
  * configure() is idempotent
  * log_event produces a queryable 'event' field
  * log_call decorator captures timing + errors
"""
import io
import json
import logging
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kotak_bot.utils import structured_log as slog  # noqa: E402


def _isolated_logger(stream: io.StringIO, name: str = "kotak_bot") -> logging.Logger:
    """Build a fresh logger that writes only to ``stream`` (no global side effects)."""
    log = logging.getLogger(name + ".isolated_" + id(stream).__str__())
    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    h = logging.StreamHandler(stream=stream)
    h.setFormatter(slog.JsonFormatter())
    log.addHandler(h)
    log.propagate = False
    return log


class TestJsonFormatter(unittest.TestCase):
    def setUp(self):
        slog._CONFIGURED = False

    def test_basic_envelope_shape(self):
        stream = io.StringIO()
        log = _isolated_logger(stream)
        log.info("hello", extra={"user": "sai", "n": 42})
        rec = json.loads(stream.getvalue().strip())
        self.assertEqual(rec["level"], "INFO")
        self.assertEqual(rec["msg"], "hello")
        self.assertEqual(rec["user"], "sai")
        self.assertEqual(rec["n"], 42)
        self.assertIn("ts", rec)
        self.assertIn("pid", rec)
        self.assertIn("module", rec)

    def test_extra_fields_flattened(self):
        stream = io.StringIO()
        log = _isolated_logger(stream)
        log.info("order", extra={
            "symbol": "NIFTY", "qty": 75, "price": 125.5, "tags": ["a", "b"],
        })
        rec = json.loads(stream.getvalue().strip())
        self.assertEqual(rec["symbol"], "NIFTY")
        self.assertEqual(rec["qty"], 75)
        self.assertEqual(rec["price"], 125.5)
        self.assertEqual(rec["tags"], ["a", "b"])

    def test_exception_captured(self):
        stream = io.StringIO()
        log = _isolated_logger(stream)
        try:
            1 / 0
        except ZeroDivisionError:
            log.exception("boom")
        rec = json.loads(stream.getvalue().strip())
        self.assertEqual(rec["level"], "ERROR")
        self.assertEqual(rec["msg"], "boom")
        self.assertEqual(rec["exc_type"], "ZeroDivisionError")
        self.assertIn("ZeroDivisionError", rec["exc"])
        self.assertIn("division by zero", rec["exc"])

    def test_configure_is_idempotent(self):
        slog.configure(json_path="data_cache/_test_runtime.jsonl", also_console=False)
        n1 = len(logging.getLogger("kotak_bot").handlers)
        slog.configure(json_path="data_cache/_test_runtime.jsonl", also_console=False)
        n2 = len(logging.getLogger("kotak_bot").handlers)
        self.assertEqual(n1, n2, "configure() must be idempotent — no handler accumulation")

    def test_log_event_produces_queryable_event(self):
        slog._CONFIGURED = False
        slog.configure(json_path="data_cache/_test_runtime.jsonl", also_console=False)
        # Patch slog.log_event to capture the call, by spying on the underlying
        # logger after configure().
        from kotak_bot.utils.structured_log import get_logger
        captured = io.StringIO()
        h = logging.StreamHandler(stream=captured)
        h.setFormatter(slog.JsonFormatter())
        root = get_logger()
        root.addHandler(h)
        try:
            slog.log_event("INFO", "order.placed", symbol="NIFTY", qty=75)
        finally:
            root.removeHandler(h)
        rec = json.loads(captured.getvalue().strip())
        self.assertEqual(rec["event"], "order.placed")
        self.assertEqual(rec["msg"], "order.placed")
        self.assertEqual(rec["symbol"], "NIFTY")
        self.assertEqual(rec["qty"], 75)


class TestLogCallDecorator(unittest.TestCase):
    def setUp(self):
        slog._CONFIGURED = False

    def test_success_emits_ok_with_timing(self):
        captured: list[dict] = []
        original = slog.log_event
        slog.log_event = lambda level, event, **kw: captured.append({"level": level, "event": event, **kw})
        try:
            @slog.log_call("my.op", level="DEBUG")
            def my_fn(x):
                return x * 2
            self.assertEqual(my_fn(21), 42)
        finally:
            slog.log_event = original
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["event"], "my.op.ok")
        self.assertIn("duration_ms", captured[0])
        self.assertGreaterEqual(captured[0]["duration_ms"], 0)

    def test_failure_emits_error_and_reraises(self):
        captured: list[dict] = []
        original = slog.log_event
        slog.log_event = lambda level, event, **kw: captured.append({"level": level, "event": event, **kw})
        try:
            @slog.log_call("my.op", level="DEBUG")
            def my_fn():
                raise ValueError("nope")
            with self.assertRaises(ValueError):
                my_fn()
        finally:
            slog.log_event = original
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["event"], "my.op.error")
        self.assertEqual(captured[0]["exc_type"], "ValueError")
        self.assertIn("nope", captured[0]["exc"])


if __name__ == "__main__":
    unittest.main()
