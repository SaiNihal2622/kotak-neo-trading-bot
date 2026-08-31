"""Session 715/1000 recovery — soft-retry transient model-provider API errors.

When a cron session dies with `unknown error, 715 (1000)`, the work didn't
complete. This script:
1. Reads local_runtime_sessions for sessions that died with 715 in the last 5 min
2. For each, looks up the original cron in local_runtime_v2_cron_definitions
3. Schedules a one-shot re-run via mavis cron create (mode: new, fresh session)
4. Marks the failed session as "recovered" in the handoff doc

This is a SOFT retry — at the cron level. A HARD retry at the LLM call level
would require Mavis runtime changes. The cron-level soft retry is sufficient
because:
- 715 is a transient upstream error, not a logic error
- A fresh session is more likely to succeed than retrying the dead one
- The work is idempotent (cron prompts are read-only on most data)

Idempotent: if the same session is already scheduled for recovery, skip.
"""
import sqlite3
import json
import os
import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path

DB = r'C:\Users\saini\.minimax\v2\sqlite\runtime-state.sqlite'
HANDOFF = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\session_handoff.md')
RECOVERY_LOG = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\session_715_recovery.jsonl')
DEDUP_SEC = 60 * 30  # don't re-recover same session within 30 min


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def already_recovered(sid: str) -> bool:
    """Check if we already scheduled recovery for this session."""
    if not RECOVERY_LOG.exists():
        return False
    cutoff = time.time() - DEDUP_SEC
    try:
        with open(RECOVERY_LOG, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if rec.get("session_id") == sid and rec.get("ts_unix", 0) > cutoff:
                        return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


def main() -> int:
    if not os.path.exists(DB):
        print(json.dumps({"ok": False, "error": f"db not found: {DB}"}))
        return 1

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # Find 715/1000 errors in last 5 min
    cutoff_ms = (time.time() - 5 * 60) * 1000
    cur.execute(
        """SELECT s.session_id, s.title, s.purpose, s.origin_cron_id, s.error_message, s.updated_at_ms
           FROM local_runtime_sessions s
           WHERE s.error_code = 50001
             AND s.updated_at_ms > ?
             AND (s.error_message LIKE '%715%' OR s.error_message LIKE '%1000%')
             AND s.archived = 0
           ORDER BY s.updated_at_ms DESC""",
        (cutoff_ms,),
    )
    seven15 = cur.fetchall()

    # Also map cron purpose to cron name
    cur.execute("SELECT cron_id, name, prompt, target_session_id FROM local_runtime_v2_cron_definitions")
    cron_by_id = {r[0]: r for r in cur.fetchall()}

    recovered: list[dict] = []
    skipped: list[dict] = []
    for sid, title, purpose, origin_cron_id, em, ts in seven15:
        if already_recovered(sid):
            skipped.append({"session_id": sid, "reason": "dedup"})
            continue

        # Find the originating cron (purpose like "cron:mavis:kotak-bot-watchdog")
        cron_name = None
        cron_prompt = None
        if purpose and purpose.startswith("cron:mavis:"):
            cron_name = purpose.split(":", 2)[-1]
        if not cron_name and origin_cron_id and origin_cron_id in cron_by_id:
            cron_name = cron_by_id[origin_cron_id][1]

        if cron_name and cron_name in [r[1] for r in cron_by_id.values()]:
            for cid, name, prompt, target_sid in cron_by_id.values():
                if name == cron_name:
                    cron_prompt = prompt
                    break
        else:
            skipped.append({"session_id": sid, "reason": f"no_cron_found: purpose={purpose} origin={origin_cron_id}"})
            continue

        # Schedule a one-shot re-run via mavis cron create
        try:
            r = subprocess.run(
                ["mavis", "cron", "once",
                 "--cron_name", f"retry-{cron_name}-{int(time.time())}",
                 "--prompt", f"RETRY of {cron_name} (715-recovery of {sid[:8]}). Run the same logic as the original prompt. {cron_prompt[:1500]}",
                 "--agent_name", "mavis",
                 "--session", "new",
                 "--after", "30s"],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode == 0:
                recovered.append({
                    "ts": now_iso(),
                    "ts_unix": time.time(),
                    "session_id": sid,
                    "cron_name": cron_name,
                    "original_prompt_len": len(cron_prompt) if cron_prompt else 0,
                    "mavis_output": r.stdout.strip()[:200],
                })
            else:
                skipped.append({"session_id": sid, "reason": f"mavis_failed: {r.stderr.strip()[:100]}"})
        except Exception as e:
            skipped.append({"session_id": sid, "reason": f"mavis_err: {str(e)[:100]}"})

    conn.close()

    # Log
    if recovered or skipped:
        RECOVERY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(RECOVERY_LOG, "a", encoding="utf-8") as f:
            for rec in recovered + skipped:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Append to handoff
    if recovered:
        try:
            HANDOFF.parent.mkdir(parents=True, exist_ok=True)
            block = [
                "",
                f"## 715-recovery @ {now_iso()}",
                f"Re-scheduled {len(recovered)} cron(s) after 715/1000 errors:",
                "",
            ]
            for rec in recovered:
                block.append(f"- `{rec['cron_name']}` (was `{rec['session_id'][:20]}`)")
            block.append("")
            with open(HANDOFF, "a", encoding="utf-8") as f:
                f.write("\n".join(block))
        except Exception as e:
            print(f"handoff write err: {e}", file=sys.stderr)

    # One-line summary
    print(
        f"SESSION-715-RECOVERY: {len(recovered)} rescheduled, {len(skipped)} skipped "
        f"(of {len(seven15)} 715/1000 errors in last 5min)"
    )
    for rec in recovered:
        print(f"  + {rec['cron_name']}  (was {rec['session_id'][:20]})")
    for rec in skipped[:5]:
        print(f"  - {rec.get('session_id', '?')[:20]}  {rec.get('reason', '?')[:60]}")
    return 0 if not recovered else 1


if __name__ == "__main__":
    sys.exit(main())
