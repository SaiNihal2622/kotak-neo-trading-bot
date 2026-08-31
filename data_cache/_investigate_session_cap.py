#!/usr/bin/env python3
"""Investigate the session-context-too-large failure pattern."""
import sqlite3
import os
import json
import datetime

DB = r'C:\Users\saini\.minimax\v2\sqlite\runtime-state.sqlite'
conn = sqlite3.connect(DB)
cur = conn.cursor()

print("=" * 70)
print("TABLES IN runtime-state.sqlite")
print("=" * 70)
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
for r in cur.fetchall():
    print(f"  {r[0]}")

print()
print("=" * 70)
print("ALL 50001 COMPACTION-FAILED SESSIONS (last 14 days)")
print("=" * 70)
now_ms = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
RECENT_MS = 14 * 24 * 60 * 60 * 1000
cur.execute("""
    SELECT session_id, title, status, updated_at_ms, error_message
    FROM local_runtime_sessions
    WHERE error_code = 50001
      AND updated_at_ms > ?
    ORDER BY updated_at_ms DESC
""", (now_ms - RECENT_MS,))
rows = cur.fetchall()
print(f"Found {len(rows)} compaction-failed sessions in last 14 days")
for sid, title, status, upd, err in rows[:20]:
    dt = datetime.datetime.fromtimestamp(upd / 1000, datetime.timezone.utc).astimezone().isoformat(timespec='seconds')
    print(f"  {dt} | {sid} | {title[:50]}")
    if err:
        print(f"    ERR: {err[:200]}")

print()
print("=" * 70)
print("DETAILS OF LATEST 2 DEAD SESSIONS (msg sizes, biggest msg, etc)")
print("=" * 70)
for sid, _, _, _, _ in rows[:2]:
    print(f"\n--- {sid} ---")
    cur.execute("""
        SELECT COUNT(*), COALESCE(SUM(LENGTH(data_json)), 0), COALESCE(MAX(LENGTH(data_json)), 0),
               COALESCE(MIN(LENGTH(data_json)), 0), COALESCE(AVG(LENGTH(data_json)), 0)
        FROM local_runtime_message_rows
        WHERE session_id = ?
    """, (sid,))
    cnt, total, mx, mn, avg = cur.fetchone()
    print(f"  Messages: {cnt}, total={total/1e6:.2f}MB, max={mx/1024:.1f}KB, min={mn/1024:.1f}KB, avg={avg/1024:.1f}KB")
    # Top 5 biggest messages
    cur.execute("""
        SELECT id, role, LENGTH(data_json), substr(data_json, 1, 200)
        FROM local_runtime_message_rows
        WHERE session_id = ?
        ORDER BY LENGTH(data_json) DESC
        LIMIT 5
    """, (sid,))
    print(f"  Top 5 biggest messages:")
    for mid, role, sz, preview in cur.fetchall():
        print(f"    {sz/1024:.1f}KB | role={role} | {preview[:150]!r}")

print()
print("=" * 70)
print("SCHEMA OF local_runtime_message_rows")
print("=" * 70)
cur.execute("PRAGMA table_info(local_runtime_message_rows)")
for r in cur.fetchall():
    print(f"  {r}")

print()
print("=" * 70)
print("SCHEMA OF local_runtime_sessions")
print("=" * 70)
cur.execute("PRAGMA table_info(local_runtime_sessions)")
for r in cur.fetchall():
    print(f"  {r}")

print()
print("=" * 70)
print("ANY CONFIG/CAP TABLE?")
print("=" * 70)
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%config%' OR name LIKE '%setting%' OR name LIKE '%cap%' OR name LIKE '%limit%' OR name LIKE '%checkpoint%')")
for r in cur.fetchall():
    print(f"  {r[0]}")

print()
print("=" * 70)
print("RECENT SUCCESSFUL SESSIONS (for comparison)")
print("=" * 70)
cur.execute("""
    SELECT s.session_id, s.title, s.status, s.updated_at_ms,
           COALESCE(SUM(LENGTH(m.data_json)), 0) as total_bytes,
           COALESCE(MAX(LENGTH(m.data_json)), 0) as max_bytes,
           COUNT(m.id) as msg_count
    FROM local_runtime_sessions s
    LEFT JOIN local_runtime_message_rows m ON s.session_id = m.session_id
    WHERE s.status NOT IN ('error')
      AND s.updated_at_ms > ?
      AND s.archived = 0
    GROUP BY s.session_id
    ORDER BY total_bytes DESC
    LIMIT 10
""", (now_ms - RECENT_MS,))
print(f"Top 10 sessions by total size (non-error, last 14d):")
for sid, title, status, upd, total, mx, cnt in cur.fetchall():
    dt = datetime.datetime.fromtimestamp(upd / 1000, datetime.timezone.utc).astimezone().isoformat(timespec='seconds')
    print(f"  {dt} | {total/1e6:.2f}MB max={mx/1024:.0f}KB msgs={cnt} | {sid} | {title[:40]}")
