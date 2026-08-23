"""Unit tests for kotak_bot.utils.metrics.

Coverage:
  * Counter increment accumulates
  * Gauge set overwrites (does not accumulate)
  * Timing list computes p50/p95/p99 correctly
  * Snapshot serializes to JSON-safe shape
  * write_jsonl appends one line per call
  * reset() wipes state
  * Tags produce distinct key series
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kotak_bot.utils import metrics as M  # noqa: E402


class TestMetrics(unittest.TestCase):
    def setUp(self):
        M.reset()

    def test_counter_increments(self):
        M.metric_inc("orders.placed")
        M.metric_inc("orders.placed")
        M.metric_inc("orders.placed", value=3.5)
        snap = M.snapshot()
        self.assertEqual(snap["counters"]["orders.placed"], 5.5)

    def test_gauge_overwrites(self):
        M.metric_gauge("open_positions", 2.0)
        M.metric_gauge("open_positions", 5.0)  # overwrite, not accumulate
        snap = M.snapshot()
        self.assertEqual(snap["gauges"]["open_positions"], 5.0)

    def test_tags_produce_distinct_series(self):
        M.metric_inc("orders.placed", tags={"side": "BUY"})
        M.metric_inc("orders.placed", tags={"side": "BUY"})
        M.metric_inc("orders.placed", tags={"side": "SELL"})
        snap = M.snapshot()
        # Tag key format is "name|tag_key=tag_value" (no quotes around value)
        buy_key = next(k for k in snap["counters"] if "side=BUY" in k)
        sell_key = next(k for k in snap["counters"] if "side=SELL" in k)
        self.assertEqual(snap["counters"][buy_key], 2)
        self.assertEqual(snap["counters"][sell_key], 1)

    def test_timing_percentiles(self):
        for v in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]:
            M.metric_timing("latency", float(v))
        snap = M.snapshot()
        stats = snap["timings"]["latency"]
        self.assertEqual(stats["n"], 10)
        self.assertEqual(stats["min"], 1.0)
        self.assertEqual(stats["max"], 10.0)
        self.assertEqual(stats["p50"], 5.5)  # median of 1..10
        self.assertEqual(stats["p95"], 9.55)

    def test_snapshot_is_json_serializable(self):
        M.metric_inc("x", tags={"k": "v"})
        M.metric_gauge("y", 1.5)
        M.metric_timing("z", 3.14)
        snap = M.snapshot()
        # Should not raise
        encoded = json.dumps(snap, default=str)
        decoded = json.loads(encoded)
        self.assertIn("counters", decoded)
        self.assertIn("gauges", decoded)
        self.assertIn("timings", decoded)

    def test_write_jsonl_appends(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "metrics.jsonl"
            M.metric_inc("a", 1)
            M.write_jsonl(str(p))
            M.metric_inc("a", 1)
            M.write_jsonl(str(p))
            lines = p.read_text(encoding="utf-8").strip().split("\n")
            self.assertEqual(len(lines), 2)
            rec1 = json.loads(lines[0])
            rec2 = json.loads(lines[1])
            self.assertEqual(rec1["counters"]["a"], 1)
            self.assertEqual(rec2["counters"]["a"], 2)

    def test_reset_clears(self):
        M.metric_inc("x", 5)
        M.reset()
        snap = M.snapshot()
        self.assertEqual(snap["counters"], {})
        self.assertEqual(snap["gauges"], {})
        self.assertEqual(snap["timings"], {})

    def test_prometheus_text_format(self):
        M.metric_inc("orders.placed", 7)
        M.metric_gauge("open_positions", 2.0)
        text = M.to_prometheus_text()
        self.assertIn("# TYPE orders.placed counter", text)
        self.assertIn("# TYPE open_positions gauge", text)
        self.assertIn("orders.placed", text)
        self.assertIn("open_positions", text)

    def test_timing_decorator(self):
        @M.timing_decorator("my.op")
        def f():
            return 42
        self.assertEqual(f(), 42)
        snap = M.snapshot()
        self.assertIn("my.op", snap["timings"])
        self.assertGreaterEqual(snap["timings"]["my.op"]["n"], 1)

    def test_timing_cap_does_not_unbounded_grow(self):
        for i in range(3000):
            M.metric_timing("bounded", float(i))
        snap = M.snapshot()
        # cap is 2000, but we drop 25% when we hit it, so we should be under 2000
        self.assertLessEqual(snap["timings"]["bounded"]["n"], 2000)


if __name__ == "__main__":
    unittest.main()
