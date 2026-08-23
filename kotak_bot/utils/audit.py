"""Production-grade audit log for trading decisions.

Why this exists
---------------
Every trading decision (open, close, hold, skip) needs to be traceable for:
  * Post-mortem analysis ("why did we enter at 09:32?")
  * Compliance / regulatory audit trails
  * Strategy debugging ("did the regime detector actually see VIX=18?")
  * Dispute resolution with the broker

The audit log is append-only JSONL with structured fields. Each record has:

  Required:
    ts           — ISO 8601 UTC with millisecond precision
    event        — short stable name (e.g. "order.placed", "order.filled",
                   "decision.open", "decision.hold", "risk.rejected")
    context      — free-form snapshot of the world at decision time (regime,
                   VIX, time, candle signal, etc.)

  Optional per event:
    symbol, side, qty, price, order_id — order details
    pnl, pnl_pct, hold_sec             — outcome / time-in-trade
    reason, evidence, score, ...       — rationale

Public API
----------
  AuditLog(path="data_cache/audit.jsonl")
      .record(event, **fields)  → write one entry, return the dict
      .query(event=None, since=None, until=None, **filters) → list[dict]
      .summary()                → {"total": N, "by_event": {...}, ...}
      .tail(n=10)               → last n entries
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _now_utc_iso() -> str:
    """ISO 8601 with millisecond precision, always UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int((time.time() % 1) * 1000):03d}Z"


class AuditLog:
    """Append-only JSONL audit log with query support."""

    def __init__(self, path: str = "data_cache/audit.jsonl", max_bytes: int = 50 * 1024 * 1024) -> None:
        self.path = Path(path)
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event: str, **fields: Any) -> dict:
        """Write one audit entry. Returns the entry dict (for chaining/logging)."""
        entry: dict[str, Any] = {
            "ts": _now_utc_iso(),
            "event": event,
            **fields,
        }
        with self._lock:
            # Check size + rotate if needed
            if self.path.exists() and self.path.stat().st_size > self.max_bytes:
                # Rotate: audit.jsonl → audit.jsonl.1 (overwrite oldest)
                rotated = self.path.with_suffix(".jsonl.1")
                if rotated.exists():
                    rotated.unlink()
                self.path.rename(rotated)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        return entry

    def tail(self, n: int = 10) -> list[dict]:
        """Return the last n entries (most recent first)."""
        if not self.path.exists():
            return []
        with self._lock:
            text = self.path.read_text(encoding="utf-8", errors="ignore")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        out: list[dict] = []
        for line in lines[-n:]:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return list(reversed(out))

    def query(
        self,
        event: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 1000,
        **filters: Any,
    ) -> list[dict]:
        """Filter entries by event name, time range, and field equality.

        Args:
            event: exact match on event name (e.g. "order.filled")
            since: ISO 8601 lower bound (inclusive)
            until: ISO 8601 upper bound (inclusive)
            limit: max results to return
            **filters: additional field equality (e.g. symbol="NIFTY", side="BUY")
        """
        if not self.path.exists():
            return []
        with self._lock:
            text = self.path.read_text(encoding="utf-8", errors="ignore")
        results: list[dict] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if event is not None and rec.get("event") != event:
                continue
            if since is not None and rec.get("ts", "") < since:
                continue
            if until is not None and rec.get("ts", "") > until:
                continue
            ok = True
            for k, v in filters.items():
                if rec.get(k) != v:
                    ok = False
                    break
            if not ok:
                continue
            results.append(rec)
            if len(results) >= limit:
                break
        return results

    def summary(self) -> dict:
        """Lightweight stats for the dashboard / health endpoint."""
        if not self.path.exists():
            return {"total": 0, "by_event": {}, "by_symbol": {}, "first_ts": None, "last_ts": None, "size_bytes": 0}
        with self._lock:
            text = self.path.read_text(encoding="utf-8", errors="ignore")
        by_event: dict[str, int] = {}
        by_symbol: dict[str, int] = {}
        first_ts = None
        last_ts = None
        total = 0
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            total += 1
            ev = rec.get("event", "?")
            by_event[ev] = by_event.get(ev, 0) + 1
            sym = rec.get("symbol") or rec.get("underlying") or "—"
            by_symbol[str(sym)] = by_symbol.get(str(sym), 0) + 1
            ts = rec.get("ts")
            if ts is not None:
                if first_ts is None or ts < first_ts:
                    first_ts = ts
                if last_ts is None or ts > last_ts:
                    last_ts = ts
        return {
            "total": total,
            "by_event": by_event,
            "by_symbol": by_symbol,
            "first_ts": first_ts,
            "last_ts": last_ts,
            "size_bytes": self.path.stat().st_size,
        }


# ---- module-level singleton ------------------------------------------------
_DEFAULT: Optional[AuditLog] = None
_DEFAULT_LOCK = threading.Lock()


def get_default() -> Optional[AuditLog]:
    return _DEFAULT


def install_default(path: str = "data_cache/audit.jsonl") -> AuditLog:
    """Install a process-wide AuditLog (singleton)."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = AuditLog(path=path)
        return _DEFAULT
