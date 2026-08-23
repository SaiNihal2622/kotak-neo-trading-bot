"""Production-grade in-process metrics registry.

Why this exists
---------------
A production bot needs to be observable in three ways:

  1. Counters — monotonic, only increase (orders placed, fills received, errors).
  2. Gauges   — point-in-time, can go up or down (open positions, cash, VIX).
  3. Timings  — distribution of how long things take (latency histograms).

These are accumulated in-process (no Prometheus dependency, no HTTP server
that needs babysitting) and exposed via:

  * ``snapshot()`` — dict for the dashboard to read on each refresh
  * ``to_prometheus_text()`` — text format for scraping by a sidecar if you
    ever add one
  * ``write_jsonl(path)`` — append a snapshot to a JSONL file for time-series
    analysis in the dashboard

Public API
----------
  metric_inc(name, value=1, tags=None)
  metric_gauge(name, value, tags=None)
  metric_timing(name, value_ms, tags=None)
  snapshot() → dict
  to_prometheus_text() → str
  write_jsonl(path) → None
  reset() → None   (test only)
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional


# ---- internal storage ------------------------------------------------------

_LOCK = threading.RLock()  # reentrant so snapshot() can be called from write_jsonl() while holding the lock
_COUNTERS: dict[tuple[str, frozenset], float] = defaultdict(float)
_GAUGES: dict[tuple[str, frozenset], float] = {}
_TIMINGS: dict[tuple[str, frozenset], list[float]] = defaultdict(list)
# Cap per-key timing list to avoid unbounded growth in long-running processes
_TIMING_CAP = 2000


def _key(name: str, tags: Optional[dict] = None) -> tuple[str, frozenset]:
    if not tags:
        return (name, frozenset())
    return (name, frozenset((str(k), str(v)) for k, v in tags.items()))


# ---- public API ------------------------------------------------------------

def metric_inc(name: str, value: float = 1.0, tags: Optional[dict] = None) -> None:
    """Increment a counter. value can be fractional (e.g. 0.5 for half-trades)."""
    with _LOCK:
        _COUNTERS[_key(name, tags)] += float(value)


def metric_gauge(name: str, value: float, tags: Optional[dict] = None) -> None:
    """Set a gauge (overwrites previous value)."""
    with _LOCK:
        _GAUGES[_key(name, tags)] = float(value)


def metric_timing(name: str, value_ms: float, tags: Optional[dict] = None) -> None:
    """Record a timing observation (ms)."""
    with _LOCK:
        lst = _TIMINGS[_key(name, tags)]
        lst.append(float(value_ms))
        if len(lst) > _TIMING_CAP:
            # Drop the oldest 25% to amortize cost
            del lst[: len(lst) // 4]


def timing_decorator(name: str, tags: Optional[dict] = None):
    """Decorator: record function duration in ms under the given metric name."""
    def deco(fn):
        import functools
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                dt_ms = (time.perf_counter() - t0) * 1000
                metric_timing(name, dt_ms, tags)
        return wrapper
    return deco


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return round(sorted_values[0], 3)
    k = (len(sorted_values) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return round(sorted_values[f], 3)
    return round(sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f), 3)


def snapshot() -> dict:
    """Return a JSON-serializable snapshot of all metrics.

    Shape::

        {
          "ts": "2026-08-23T13:14:00.123+05:30",
          "counters": { "name": value, ... },
          "gauges":   { "name": value, ... },
          "timings":  {
              "name": {
                "n": 42, "min": 1.2, "p50": 3.4, "p95": 8.9, "p99": 12.1, "max": 15.0
              },
              ...
          }
        }
    """
    with _LOCK:
        counters = {f"{n}|{'|'.join(f'{k}={v}' for k, v in sorted(tags))}" if tags else n: v
                    for (n, tags), v in _COUNTERS.items()}
        gauges = {f"{n}|{'|'.join(f'{k}={v}' for k, v in sorted(tags))}" if tags else n: v
                  for (n, tags), v in _GAUGES.items()}
        timings = {}
        for (n, tags), lst in _TIMINGS.items():
            if not lst:
                continue
            s = sorted(lst)
            timings[f"{n}|{'|'.join(f'{k}={v}' for k, v in sorted(tags))}" if tags else n] = {
                "n": len(s),
                "min": round(s[0], 3),
                "p50": _percentile(s, 0.50),
                "p95": _percentile(s, 0.95),
                "p99": _percentile(s, 0.99),
                "max": round(s[-1], 3),
            }
    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
              + f".{int((time.time() % 1) * 1000):03d}",
        "epoch": int(time.time()),
        "counters": dict(sorted(counters.items())),
        "gauges": dict(sorted(gauges.items())),
        "timings": dict(sorted(timings.items())),
    }


def to_prometheus_text() -> str:
    """Render metrics in Prometheus text exposition format (best-effort)."""
    snap = snapshot()
    lines: list[str] = []
    # Counters
    seen: set[str] = set()
    for k, v in snap["counters"].items():
        name = k.split("|", 1)[0]
        if name not in seen:
            lines.append(f"# TYPE {name} counter")
            seen.add(name)
        labels = _prom_labels(k)
        lines.append(f"{name}{labels} {v}")
    seen.clear()
    for k, v in snap["gauges"].items():
        name = k.split("|", 1)[0]
        if name not in seen:
            lines.append(f"# TYPE {name} gauge")
            seen.add(name)
        labels = _prom_labels(k)
        lines.append(f"{name}{labels} {v}")
    seen.clear()
    for k, stats in snap["timings"].items():
        name = k.split("|", 1)[0]
        if name not in seen:
            lines.append(f"# TYPE {name}_ms summary")
            seen.add(name)
        labels = _prom_labels(k)
        lines.append(f'{name}_ms_count{labels} {stats["n"]}')
        lines.append(f'{name}_ms_sum{labels} {sum(_TIMINGS[_key_from_full(k)]) if False else 0}')
        for q, v in (("0.5", stats["p50"]), ("0.95", stats["p95"]), ("0.99", stats["p99"])):
            lines.append(f'{name}_ms{{quantile="{q}"{_prom_label_suffix(labels)}}} {v}')
    return "\n".join(lines) + "\n"


def _prom_labels(full: str) -> str:
    if "|" not in full:
        return ""
    parts = full.split("|", 1)[1].split("|")
    pairs = []
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
            pairs.append(f'{k}="{v}"')
    return "{" + ",".join(pairs) + "}" if pairs else ""


def _prom_label_suffix(labels: str) -> str:
    """Insert a quantile label inside an existing {...} block, or empty string."""
    if not labels or labels in ("{}", ""):
        return ""
    if labels.startswith("{") and labels.endswith("}"):
        return "," + labels[1:-1]
    return labels


def _key_from_full(full: str):
    """Reverse-engineer the (name, tags) key from a serialized metric name."""
    if "|" not in full:
        return (full, frozenset())
    name, rest = full.split("|", 1)
    tags = frozenset(tuple(p.split("=", 1)) for p in rest.split("|") if "=" in p)
    return (name, tags)


def write_jsonl(path: str) -> None:
    """Append a snapshot to a JSONL file (one JSON per line)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        snap = snapshot()
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(snap, default=str) + "\n")


def reset() -> None:
    """Test-only: wipe all metrics."""
    with _LOCK:
        _COUNTERS.clear()
        _GAUGES.clear()
        _TIMINGS.clear()


# ---- self-test -------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    metric_inc("orders.placed", 1, {"side": "BUY"})
    metric_inc("orders.placed", 1, {"side": "BUY"})
    metric_inc("orders.placed", 1, {"side": "SELL"})
    metric_gauge("open_positions", 2.0)
    for ms in (1.2, 2.5, 3.1, 4.8, 9.0, 14.2):
        metric_timing("risk.evaluate_ms", ms)
    import sys
    print(json.dumps(snapshot(), indent=2))
    sys.exit(0)
