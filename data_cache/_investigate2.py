#!/usr/bin/env python3
"""Look at the dead session that just died - fix column names."""
import sqlite3
import json
import datetime
import os

DB = r'C:\Users\saini\.minimax\v2\sqlite\runtime-state.sqlite'
conn = sqlite3.connect(DB)
cur = conn.cursor()

# First check token table schema
print("=" * 70)
print("TOKEN TABLE SCHEMA")
print("=" * 70)
cur.execute("PRAGMA table_info(local_runtime_token_usage)")
for r in cur.fetchall():
    print(f"  {r}")

DEAD_IDS = [
    'mvs_fddaffedef47489491056112be947e73',
    'mvs_47cf562d0ce2451aad1d6be4aa97c51b',
    'mvs_d36c7630216c4768b73eb11633c4be10',
    'mvs_5487fafc4a0d44038b6c9d4042c98a7d',
]

print()
print("=" * 70)
print("DEAD SESSION DETAILS")
print("=" * 70)
for sid in DEAD_IDS:
    cur.execute("""
        SELECT s.title, s.error_message, s.updated_at_ms, s.created_at_ms,
               COALESCE(SUM(LENGTH(m.data_json)), 0) as total_bytes,
               COALESCE(MAX(LENGTH(m.data_json)), 0) as max_bytes,
               COUNT(m.id) as msg_count,
               (SELECT MAX(created_at_ms) FROM local_runtime_message_rows WHERE session_id = s.session_id) as last_msg_ms
        FROM local_runtime_sessions s
        LEFT JOIN local_runtime_message_rows m ON s.session_id = m.session_id
        WHERE s.session_id = ?
        GROUP BY s.session_id
    """, (sid,))
    r = cur.fetchone()
    if r:
        title, err, upd, created, total, mx, cnt, last_msg = r
        print(f"\n--- {sid} ---")
        print(f"  Title: {title}")
        if created:
            print(f"  Created: {datetime.datetime.fromtimestamp(created/1000).astimezone().isoformat(timespec='seconds')}")
        if upd:
            print(f"  Updated: {datetime.datetime.fromtimestamp(upd/1000).astimezone().isoformat(timespec='seconds')}")
        if last_msg:
            print(f"  Last msg: {datetime.datetime.fromtimestamp(last_msg/1000).astimezone().isoformat(timespec='seconds')}")
        print(f"  Total: {total/1e6:.2f}MB, max msg: {mx/1024:.1f}KB, msg count: {cnt}")
        # Token usage - check actual columns
        cur.execute("PRAGMA table_info(local_runtime_token_usage)")
        cols = [c[1] for c in cur.fetchall()]
        # Build select from non-null columns
        sel = ", ".join([f"COALESCE(SUM({c}),0)" for c in cols if 'token' in c.lower() and 'id' not in c.lower()])
        cur.execute(f"SELECT {sel}, COUNT(*) FROM local_runtime_token_usage WHERE session_id = ?", (sid,))
        tu = cur.fetchone()
        print(f"  Token usage sums (cols: {[c for c in cols if 'token' in c.lower()]}): {tu}")

        # Find the BIGGEST message and what role/source it is
        cur.execute("""
            SELECT id, role, source, LENGTH(data_json), substr(data_json, 1, 300)
            FROM local_runtime_message_rows
            WHERE session_id = ?
            ORDER BY LENGTH(data_json) DESC
            LIMIT 1
        """, (sid,))
        biggest = cur.fetchone()
        if biggest:
            print(f"  BIGGEST MSG: id={biggest[0]} role={biggest[1]} source={biggest[2]} size={biggest[3]/1024:.1f}KB")
            print(f"    preview: {biggest[4][:200]!r}")

        # Show count of messages > 100KB
        cur.execute("""
            SELECT COUNT(*) FROM local_runtime_message_rows
            WHERE session_id = ? AND LENGTH(data_json) > 100000
        """, (sid,))
        big_count = cur.fetchone()[0]
        cur.execute("""
            SELECT COUNT(*) FROM local_runtime_message_rows
            WHERE session_id = ? AND LENGTH(data_json) > 500000
        """, (sid,))
        huge_count = cur.fetchone()[0]
        print(f"  Messages > 100KB: {big_count}, > 500KB: {huge_count}")
