#!/usr/bin/env python3
"""Test session_janitor strip on a synthetic bloated session - clean version."""
import sqlite3
import json
import sys
import os
import datetime
import subprocess

DB = r'C:\Users\saini\.minimax\v2\sqlite\runtime-state.sqlite'
TEST_SESSION_ID = 'mvs_test_janitor_aaa_bbb_ccc_ddd_eee'

def setup_test_session():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("DELETE FROM local_runtime_message_rows WHERE session_id = ?", (TEST_SESSION_ID,))
    cur.execute("DELETE FROM local_runtime_sessions WHERE session_id = ?", (TEST_SESSION_ID,))
    now_ms = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
    cur.execute("""
        INSERT INTO local_runtime_sessions
        (session_id, record_json, updated_at_ms, columnar_version, agent_name, runtime,
         session_type, status, archived, visibility, session_kind, purpose_kind,
         workspace_dir, is_default_workspace, title, error_message, error_code, extra_data_json)
        VALUES (?, '{}', ?, 0, 'mavis', 'pi-agent', 0, 'started', 0, 'visible',
                'unknown', '', 'C:\\test', 0, 'Test Janitor', NULL, NULL, '{}')
    """, (TEST_SESSION_ID, now_ms))
    for i in range(60):
        role = 'user' if i % 2 == 0 else 'assistant'
        created = now_ms - (60 - i) * 60_000
        if role == 'user':
            data = {"role": "user", "msg_content": f"User message {i}", "timestamp": created}
        else:
            data = {
                "role": "assistant",
                "msg_content": f"Assistant conclusion for turn {i}: analysis done.",
                "timestamp": created,
                "tool_calls": [{
                    "tool_name": "bash",
                    "tool_call_args": '{"command": "ls"}',
                    "tool_call_result_data": "X" * 50_000,
                }]
            }
        cur.execute("""
            INSERT INTO local_runtime_message_rows
            (session_id, msg_id, role, turn_id, created_at_ms, data_json, source, source_context_json)
            VALUES (?, ?, ?, NULL, ?, ?, 'api', NULL)
        """, (TEST_SESSION_ID, f"msg_{i}", role, created, json.dumps(data)))
    conn.commit()
    conn.close()

def measure_session(label):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), SUM(LENGTH(data_json)) FROM local_runtime_message_rows WHERE session_id = ?", (TEST_SESSION_ID,))
    cnt, total = cur.fetchone()
    cur.execute("""
        SELECT json_extract(data_json, '$.tool_calls[0].tool_call_result_data') as trd
        FROM local_runtime_message_rows
        WHERE session_id = ? AND role = 'assistant'
        ORDER BY created_at_ms ASC
    """, (TEST_SESSION_ID,))
    rows = cur.fetchall()
    stripped = sum(1 for (trd,) in rows if isinstance(trd, str) and "stripped" in trd)
    original = sum(1 for (trd,) in rows if isinstance(trd, str) and "stripped" not in trd)
    conn.close()
    print(f"{label}: msgs={cnt} total={total/1024/1024:.2f}MB | assistant_tool_results: stripped={stripped} original={original}")

def cleanup():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("DELETE FROM local_runtime_message_rows WHERE session_id = ?", (TEST_SESSION_ID,))
    cur.execute("DELETE FROM local_runtime_sessions WHERE session_id = ?", (TEST_SESSION_ID,))
    conn.commit()
    conn.close()
    print(f"Cleaned up test session {TEST_SESSION_ID}")

print("=" * 60)
print("TEST: session_janitor strip on a 60-msg bloated session")
print("=" * 60)
setup_test_session()
measure_session("BEFORE")
proc = subprocess.run([sys.executable, r"C:\Users\saini\.minimax\agents\mavis\scripts\session_janitor.py"],
                     capture_output=True, text=True, timeout=60)
# Print only first 2 lines of janitor output
stdout_lines = proc.stdout.split('\n')
for line in stdout_lines[:3]:
    print(f"  [janitor] {line}")
if proc.returncode != 0:
    print(f"  [janitor stderr] {proc.stderr}")
measure_session("AFTER ")
cleanup()
print("=" * 60)
print("DONE")
print("=" * 60)
