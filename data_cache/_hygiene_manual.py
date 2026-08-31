"""Manual fallback for session_hygiene.py file write."""
import os
import json
import datetime
import sqlite3
import sys

DB = r'C:\Users\saini\.minimax\v2\sqlite\runtime-state.sqlite'
OUT = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\session_hygiene.json'
PREV = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\session_hygiene.prev.json'
TEST = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\session_hygiene.test.json'

WARN_BIG_MSG = 500_000
WARN_TOTAL = 4_000_000
FAIL_BIG_MSG = 1_500_000
FAIL_TOTAL = 6_000_000
RECENT_MS = 7 * 24 * 60 * 60 * 1000

conn = sqlite3.connect(DB)
cur = conn.cursor()
now_ms = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)

cur.execute(
    """
    SELECT session_id, agent_name, title, status, updated_at_ms, error_code, error_message
    FROM local_runtime_sessions
    WHERE updated_at_ms > ? AND archived = 0
      AND status IN ('started', 'finished', 'aborted', 'interrupted', 'error')
    ORDER BY updated_at_ms DESC
    """,
    (now_ms - RECENT_MS,),
)
sessions = cur.fetchall()

findings = []
for sid, agent, title, status, upd, err_code, err_msg in sessions:
    cur.execute(
        'SELECT COUNT(*), COALESCE(SUM(LENGTH(data_json)), 0), COALESCE(MAX(LENGTH(data_json)), 0) FROM local_runtime_message_rows WHERE session_id = ?',
        (sid,),
    )
    msg_count, total_bytes, max_bytes = cur.fetchone()
    cur.execute(
        'SELECT COALESCE(SUM(input_tokens + output_tokens + cache_read_tokens), 0) FROM local_runtime_token_usage WHERE session_id = ?',
        (sid,),
    )
    total_tokens = cur.fetchone()[0]
    severity = 'ok'
    reasons = []
    if max_bytes >= FAIL_BIG_MSG or total_bytes >= FAIL_TOTAL or status == 'error':
        severity = 'fail'
        if max_bytes >= FAIL_BIG_MSG:
            reasons.append('single message %.1fMB >= %.1fMB' % (max_bytes / 1e6, FAIL_BIG_MSG / 1e6))
        if total_bytes >= FAIL_TOTAL:
            reasons.append('total %.1fMB >= %.1fMB' % (total_bytes / 1e6, FAIL_TOTAL / 1e6))
        if status == 'error':
            em = (err_msg or '')[:80]
            reasons.append('session in error state: ' + em)
    elif max_bytes >= WARN_BIG_MSG or total_bytes >= WARN_TOTAL:
        severity = 'warn'
        if max_bytes >= WARN_BIG_MSG:
            reasons.append('single message %.1fMB >= %.1fMB' % (max_bytes / 1e6, WARN_BIG_MSG / 1e6))
        if total_bytes >= WARN_TOTAL:
            reasons.append('total %.1fMB >= %.1fMB' % (total_bytes / 1e6, WARN_TOTAL / 1e6))
    if severity != 'ok':
        findings.append({
            'session_id': sid,
            'agent': agent,
            'title': (title or '')[:80],
            'status': status,
            'msg_count': msg_count,
            'total_json_mb': round(total_bytes / 1e6, 2),
            'biggest_msg_kb': round(max_bytes / 1024, 1),
            'total_tokens': total_tokens,
            'severity': severity,
            'reasons': reasons,
            'updated_ms_ago': (now_ms - upd) / 1000 if upd else None,
        })

cur.execute(
    'SELECT COUNT(*) FROM local_runtime_sessions WHERE error_code = 50001 AND updated_at_ms > ?',
    (now_ms - RECENT_MS,),
)
compaction_fail_count = cur.fetchone()[0]
conn.close()

report = {
    'ok': True,
    'ts': now_ms,
    'ts_iso': datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec='seconds'),
    'thresholds': {
        'warn_big_msg_mb': WARN_BIG_MSG / 1e6,
        'warn_total_mb': WARN_TOTAL / 1e6,
        'fail_big_msg_mb': FAIL_BIG_MSG / 1e6,
        'fail_total_mb': FAIL_TOTAL / 1e6,
    },
    'compaction_fail_count_7d': compaction_fail_count,
    'active_session_count': len(sessions),
    'findings': findings,
}

# Rotate: current -> .prev if current is not a marker
current_data = None
try:
    with open(OUT, 'r', encoding='utf-8') as f:
        current_data = f.read()
except Exception as e:
    print('read current failed:', e, file=sys.stderr)

if current_data and 'MARKER_BEFORE_SCRIPT_RUN' not in current_data and 'manual_fallback_marker' not in current_data:
    with open(PREV, 'w', encoding='utf-8') as f:
        f.write(current_data)
    print('rotated current -> .prev (size=%d)' % len(current_data))
elif current_data and ('MARKER_BEFORE_SCRIPT_RUN' in current_data or 'manual_fallback_marker' in current_data):
    print('skipping rotation: current has marker')

# Write new report
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(report, f, indent=2, ensure_ascii=False)
print('wrote new report to OUT, size =', os.path.getsize(OUT))

# Clean up test file
try:
    if os.path.exists(TEST):
        os.remove(TEST)
        print('removed test file')
except Exception as e:
    print('test file cleanup:', e, file=sys.stderr)

fails = [x for x in findings if x['severity'] == 'fail']
warns = [x for x in findings if x['severity'] == 'warn']
print('HYGIENE: %d findings (%d fail, %d warn) of %d active sessions; %d compaction-fail sessions in last 7d' % (len(findings), len(fails), len(warns), len(sessions), compaction_fail_count))
