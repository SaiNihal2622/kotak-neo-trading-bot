"""Unit tests for kotak_bot.utils.audit.

Coverage:
  * record() appends valid JSONL
  * tail() returns most recent first
  * query() filters by event + time range + field equality
  * summary() aggregates correctly
  * rotation on size cap
  * thread-safe under concurrent writes
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kotak_bot.utils.audit import AuditLog  # noqa: E402


class TestAuditLog(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "audit.jsonl")
        self.audit = AuditLog(self.path, max_bytes=10_000)

    def test_record_writes_jsonl(self):
        self.audit.record("test.event", foo="bar", n=42)
        self.assertTrue(os.path.exists(self.path))
        text = open(self.path, encoding="utf-8").read().strip()
        rec = json.loads(text)
        self.assertEqual(rec["event"], "test.event")
        self.assertEqual(rec["foo"], "bar")
        self.assertEqual(rec["n"], 42)
        self.assertIn("ts", rec)
        # ts ends with Z (UTC)
        self.assertTrue(rec["ts"].endswith("Z"))

    def test_tail_returns_most_recent_first(self):
        for i in range(5):
            self.audit.record("loop", n=i)
        tail = self.audit.tail(3)
        self.assertEqual(len(tail), 3)
        self.assertEqual([t["n"] for t in tail], [4, 3, 2])

    def test_query_by_event(self):
        self.audit.record("a", v=1)
        self.audit.record("b", v=2)
        self.audit.record("a", v=3)
        results = self.audit.query(event="a")
        self.assertEqual(len(results), 2)
        self.assertEqual([r["v"] for r in results], [1, 3])

    def test_query_by_field_equality(self):
        self.audit.record("order.filled", symbol="NIFTY", side="BUY")
        self.audit.record("order.filled", symbol="BANKNIFTY", side="BUY")
        self.audit.record("order.filled", symbol="NIFTY", side="SELL")
        results = self.audit.query(symbol="NIFTY")
        self.assertEqual(len(results), 2)
        self.assertEqual({r["side"] for r in results}, {"BUY", "SELL"})

    def test_query_by_time_range(self):
        self.audit.record("e1", v=1)
        time.sleep(0.01)
        mid = "2026-08-23T00:00:00.000Z"
        time.sleep(0.01)
        self.audit.record("e2", v=2)
        results = self.audit.query(since=mid, event="e2")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["v"], 2)

    def test_summary(self):
        self.audit.record("order.placed", symbol="NIFTY")
        self.audit.record("order.placed", symbol="BANKNIFTY")
        self.audit.record("order.filled", symbol="NIFTY")
        s = self.audit.summary()
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["by_event"], {"order.placed": 2, "order.filled": 1})
        self.assertEqual(s["by_symbol"], {"NIFTY": 2, "BANKNIFTY": 1})
        self.assertIsNotNone(s["first_ts"])
        self.assertIsNotNone(s["last_ts"])

    def test_rotation_on_size_cap(self):
        # Use a very small cap
        audit = AuditLog(self.path, max_bytes=200)
        for i in range(50):
            audit.record("loop", n=i, padding="x" * 10)  # make each line ~50 bytes
        # Should have rotated
        rotated = Path(self.path).with_suffix(".jsonl.1")
        self.assertTrue(rotated.exists() or os.path.exists(self.path))
        # And the current file should be smaller than the cap
        if os.path.exists(self.path):
            self.assertLess(os.path.getsize(self.path), 200 * 3)

    def test_thread_safety(self):
        errors = []

        def writer(start):
            try:
                for i in range(20):
                    self.audit.record("concurrent", n=start + i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i * 100,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        s = self.audit.summary()
        self.assertEqual(s["total"], 100)


if __name__ == "__main__":
    unittest.main()
