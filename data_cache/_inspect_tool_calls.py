#!/usr/bin/env python3
"""Look at what's actually in the giant tool_calls arguments."""
import sqlite3
import json
import datetime

DB = r'C:\Users\saini\.minimax\v2\sqlite\runtime-state.sqlite'
conn = sqlite3.connect(DB)
cur = conn.cursor()

# Look at the 3.6MB tool call
sid = 'mvs_47cf562d0ce2451aad1d6be4aa97c51b'
cur.execute("""
    SELECT data_json FROM local_runtime_message_rows
    WHERE id = 88884
""")
r = cur.fetchone()
d = json.loads(r[0])
print("=" * 70)
print(f"MESSAGE 88884 (3.6MB) — full tool_calls inspection")
print("=" * 70)
print(f"usage: {d.get('usage')}")
print(f"context_window: {d.get('usage', {}).get('context_window')}")
print(f"input_tokens: {d.get('usage', {}).get('input_tokens')}")
print(f"output_tokens: {d.get('usage', {}).get('output_tokens')}")
print(f"thinking_duration_ms: {d.get('thinking_duration_ms')}")

tcs = d.get('tool_calls', [])
for i, tc in enumerate(tcs):
    print(f"\ntool_call[{i}]:")
    print(f"  top-level keys: {list(tc.keys()) if isinstance(tc, dict) else type(tc)}")
    if isinstance(tc, dict):
        for k, v in tc.items():
            if isinstance(v, str):
                print(f"    {k} (str, {len(v)}B): {v[:200]!r}")
                if len(v) > 200:
                    print(f"      ... [{len(v)-200} more chars]")
                    print(f"      END: ...{v[-100:]!r}")
            elif isinstance(v, dict):
                print(f"    {k} (dict, {len(json.dumps(v))}B serialized): keys = {list(v.keys())}")
                for k2, v2 in v.items():
                    if isinstance(v2, str):
                        print(f"      {k2}: ({len(v2)}B) {v2[:150]!r}")
                    else:
                        print(f"      {k2}: {v2}")
            else:
                print(f"    {k} ({type(v).__name__}): {v}")

# Now look at the other big one
cur.execute("""
    SELECT data_json FROM local_runtime_message_rows
    WHERE session_id = ? AND id = 88733
""", (sid,))
r = cur.fetchone()
d = json.loads(r[0])
print()
print("=" * 70)
print(f"MESSAGE 88733 (898KB) — second biggest")
print("=" * 70)
print(f"usage: {d.get('usage')}")
tcs = d.get('tool_calls', [])
for i, tc in enumerate(tcs):
    if isinstance(tc, dict):
        for k, v in tc.items():
            if isinstance(v, str):
                print(f"  {k} (str, {len(v)}B): {v[:200]!r}")
            elif isinstance(v, dict):
                args_str = json.dumps(v)
                print(f"  {k} (dict, {len(args_str)}B serialized): keys = {list(v.keys())}")
                for k2, v2 in v.items():
                    if isinstance(v2, str):
                        print(f"    {k2}: ({len(v2)}B) {v2[:150]!r}")
                    else:
                        print(f"    {k2}: {v2}")
            else:
                print(f"  {k} ({type(v).__name__}): {v}")

# Also check how the context_window field is set across all messages in a dead session
print()
print("=" * 70)
print("CONTEXT WINDOW USAGE OVER TIME — DEAD SESSION")
print("=" * 70)
cur.execute("""
    SELECT json_extract(data_json, '$.usage.context_window') as ctx,
           json_extract(data_json, '$.usage.input_tokens') as inp,
           json_extract(data_json, '$.usage.output_tokens') as out,
           json_extract(data_json, '$.usage.cache_read') as cr,
           json_extract(data_json, '$.usage.total_tokens') as tt
    FROM local_runtime_message_rows
    WHERE session_id = ?
      AND json_extract(data_json, '$.usage.context_window') IS NOT NULL
    ORDER BY created_at_ms DESC
    LIMIT 10
""", (sid,))
for r in cur.fetchall():
    print(f"  ctx={r[0]}, in={r[1]}, out={r[2]}, cache_read={r[3]}, total={r[4]}")
