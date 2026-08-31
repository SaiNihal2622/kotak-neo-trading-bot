#!/usr/bin/env python3
"""Examine the giant thinking_content in dead sessions."""
import sqlite3
import json
import datetime

DB = r'C:\Users\saini\.minimax\v2\sqlite\runtime-state.sqlite'
conn = sqlite3.connect(DB)
cur = conn.cursor()

# Look at the biggest message in the dead "Fix" session
sid = 'mvs_47cf562d0ce2451aad1d6be4aa97c51b'

print("=" * 70)
print("MESSAGE STRUCTURE OF BIGGEST MESSAGES IN DEAD SESSIONS")
print("=" * 70)

# Check field breakdown of all big messages
cur.execute("""
    SELECT id, LENGTH(data_json),
           json_extract(data_json, '$.role') as role,
           json_extract(data_json, '$.source') as source,
           LENGTH(json_extract(data_json, '$.msg_content')) as content_len,
           LENGTH(json_extract(data_json, '$.thinking_content')) as thinking_len,
           LENGTH(json_extract(data_json, '$.tool_calls')) as tool_calls_len,
           json_array_length(json_extract(data_json, '$.tool_calls')) as tool_call_count
    FROM local_runtime_message_rows
    WHERE session_id = ?
      AND LENGTH(data_json) > 100000
    ORDER BY LENGTH(data_json) DESC
    LIMIT 10
""", (sid,))

print(f"\n{sid} - top 10 big messages:")
for r in cur.fetchall():
    mid, total, role, source, content_len, thinking_len, tool_calls_len, tc_count = r
    print(f"  msg id={mid} total={total/1024:.0f}KB | content={content_len/1024:.0f}KB thinking={thinking_len/1024:.0f}KB tool_calls={tool_calls_len/1024:.0f}KB ({tc_count} calls) | {role}/{source}")

# Across ALL recent dead sessions, find which field is the biggest contributor
print()
print("=" * 70)
print("FIELD CONTRIBUTION TO DEAD SESSIONS' BIG MESSAGES")
print("=" * 70)

cur.execute("""
    SELECT
       COUNT(*) as big_msg_count,
       SUM(LENGTH(data_json)) as total_bytes,
       SUM(LENGTH(json_extract(data_json, '$.msg_content'))) as content_bytes,
       SUM(LENGTH(json_extract(data_json, '$.thinking_content'))) as thinking_bytes,
       SUM(LENGTH(json_extract(data_json, '$.tool_calls'))) as tool_bytes
    FROM local_runtime_message_rows
    WHERE LENGTH(data_json) > 100000
      AND session_id IN (
        'mvs_fddaffedef47489491056112be947e73',
        'mvs_47cf562d0ce2451aad1d6be4aa97c51b',
        'mvs_d36c7630216c4768b73eb11633c4be10',
        'mvs_5487fafc4a0d44038b6c9d4042c98a7d'
      )
""")
r = cur.fetchone()
print(f"  big_msg_count: {r[0]}")
print(f"  total bytes: {r[1]/1024/1024:.2f}MB")
print(f"  msg_content: {r[2]/1024/1024:.2f}MB ({r[2]*100/r[1]:.1f}%)")
print(f"  thinking_content: {r[3]/1024/1024:.2f}MB ({r[3]*100/r[1]:.1f}%)")
print(f"  tool_calls: {r[4]/1024/1024:.2f}MB ({r[4]*100/r[1]:.1f}%)")
print(f"  (other fields: {(r[1]-r[2]-r[3]-r[4])/1024/1024:.2f}MB ({(r[1]-r[2]-r[3]-r[4])*100/r[1]:.1f}%))")

# Is thinking_content a separate field the model API returns?
print()
print("=" * 70)
print("IS THINKING_CONTENT A SEPARATE FIELD?")
print("=" * 70)
# Sample one big message and look at the JSON keys
cur.execute("""
    SELECT data_json FROM local_runtime_message_rows
    WHERE session_id = ? AND LENGTH(data_json) > 1000000
    LIMIT 1
""", (sid,))
r = cur.fetchone()
if r:
    d = json.loads(r[0])
    print(f"  Top-level keys: {list(d.keys())}")
    for k, v in d.items():
        if isinstance(v, str):
            print(f"    {k} (str): {len(v)} chars, preview: {v[:80]!r}")
        elif isinstance(v, list):
            print(f"    {k} (list): {len(v)} items")
        elif isinstance(v, dict):
            print(f"    {k} (dict): keys {list(v.keys())[:5]}")
        else:
            print(f"    {k} ({type(v).__name__}): {v}")
