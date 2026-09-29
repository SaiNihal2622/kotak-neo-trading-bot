"""Event store backed by SQLite (WAL mode).

The event log is the source of truth. State projections are derived from
this log. Writers append events in transactions; readers query events
and apply them to compute current state.

Schema:
- events: append-only log of all events
- snapshot: periodic state snapshot (every N events) for fast startup

Concurrency:
- SQLite WAL mode = multiple readers + one writer
- All writes via this store's `append(event)` method, serialized internally
- No file locks at the application level
"""
from __future__ import annotations

import sqlite3
import json
import threading
from pathlib import Path
from typing import Optional
from datetime import datetime

from ..domain.events import Event, EventType
from ..domain.state import StateProjection


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    actor TEXT NOT NULL,
    correlation_id TEXT,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_corid ON events(correlation_id);

CREATE TABLE IF NOT EXISTS snapshot (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    ts TEXT NOT NULL,
    last_event_id TEXT NOT NULL,
    state_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projections (
    name TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    data_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    details_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
"""


class EventStore:
    """SQLite-backed event store. Thread-safe."""

    def __init__(self, db_path: str = "data_cache/state.db", use_wal: bool = True):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, timeout=30, isolation_level=None, check_same_thread=False)
        if use_wal:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self):
        with self._lock:
            self._conn.close()

    def append(self, event: Event) -> None:
        """Append a single event. Atomic."""
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    "INSERT INTO events (id, ts, type, actor, correlation_id, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        event.id,
                        event.ts,
                        event.type.value,
                        event.actor,
                        event.correlation_id,
                        json.dumps(event.payload, default=str),
                    ),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def append_batch(self, events: list[Event]) -> None:
        """Append multiple events in a single transaction (for atomic plan execution)."""
        if not events:
            return
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.executemany(
                    "INSERT INTO events (id, ts, type, actor, correlation_id, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (e.id, e.ts, e.type.value, e.actor, e.correlation_id, json.dumps(e.payload, default=str))
                        for e in events
                    ],
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def events_since(self, since_id: str = "", types: Optional[list[EventType]] = None, limit: int = 10000) -> list[Event]:
        """Read events from the log, optionally filtered by type."""
        sql = "SELECT id, ts, type, actor, correlation_id, payload_json FROM events WHERE 1=1"
        params = []
        if since_id:
            # Use rowid order so "since" is monotonic
            sql += " AND rowid > COALESCE((SELECT rowid FROM events WHERE id = ?), 0)"
            params.append(since_id)
        if types:
            placeholders = ",".join("?" for _ in types)
            sql += f" AND type IN ({placeholders})"
            params.extend(t.value for t in types)
        sql += " ORDER BY rowid ASC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [
            Event(
                id=r[0],
                ts=r[1],
                type=EventType(r[2]),
                actor=r[3],
                correlation_id=r[4] or "",
                payload=json.loads(r[5]),
            )
            for r in rows
        ]

    def all_events(self, limit: int = 100000) -> list[Event]:
        """Load ALL events. Used for replay/rebuild."""
        return self.events_since(limit=limit)

    def last_event_id(self) -> str:
        with self._lock:
            row = self._conn.execute("SELECT id FROM events ORDER BY rowid DESC LIMIT 1").fetchone()
        return row[0] if row else ""

    def save_projection(self, name: str, data: dict) -> None:
        """Save a derived projection (UI snapshot, audit view, etc.)."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO projections (name, ts, data_json) VALUES (?, ?, ?)",
                (name, datetime.utcnow().isoformat(), json.dumps(data, default=str)),
            )

    def load_projection(self, name: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT data_json, ts FROM projections WHERE name = ?", (name,)
            ).fetchone()
        if not row:
            return None
        return json.loads(row[0])

    def save_snapshot(self, last_event_id: str, state: StateProjection) -> None:
        """Save a full state snapshot for fast startup."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO snapshot (id, ts, last_event_id, state_json) VALUES (1, ?, ?, ?)",
                (datetime.utcnow().isoformat(), last_event_id, json.dumps(state.snapshot(), default=str)),
            )

    def load_snapshot(self) -> Optional[tuple[str, dict]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT last_event_id, state_json FROM snapshot WHERE id = 1"
            ).fetchone()
        if not row:
            return None
        return row[0], json.loads(row[1])

    def audit(self, actor: str, action: str, details: dict = None) -> None:
        """Write to audit_log. Used by force-actions and admin actions."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit_log (ts, actor, action, details_json) VALUES (?, ?, ?, ?)",
                (datetime.utcnow().isoformat(), actor, action, json.dumps(details or {}, default=str)),
            )

    def build_state_projection(self) -> StateProjection:
        """Rebuild state projection from events.

        Optimization: load snapshot if recent, then replay events since
        snapshot. For now, full replay (events are few enough).
        """
        proj = StateProjection()
        for event in self.all_events():
            proj.apply(event)
        return proj


# Convenience for callers
_global_store: Optional[EventStore] = None


def get_store(db_path: str = None) -> EventStore:
    """Get the global event store. Initializes on first call."""
    global _global_store
    if _global_store is None:
        path = db_path or "data_cache/state.db"
        _global_store = EventStore(path)
    return _global_store