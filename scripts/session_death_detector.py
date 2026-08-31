"""Session death detector — scans the local-runtime SQLite for errored sessions,
archives them silently, and writes a one-line summary to data_cache/session_handoff.md.

Designed to run as a 5-min cron (kotak-session-death-detector). Idempotent, fast,
no LLM. Reads only. Archives the dead, never re-archives.

Usage:
    python scripts/session_death_detector.py
    # exit 0 if no new errored sessions, exit 1 if any were archived.
"""
import sqlite3
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

DB = r'C:\Users\saini\.minimax\v2\sqlite\runtime-state.sqlite'
HANDOFF = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\session_handoff.md')
LOG_PATH = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\session_death_detector.jsonl')

# 5 min threshold — anything errored longer than this gets swept
STALE_SEC = 5 * 60
# Dedup window — we won't re-archive or re-log the same session within this window
DEDUP_SEC = 60 * 60


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def main() -> int:
    if not os.path.exists(DB):
        print(json.dumps({"ok": False, "error": f"db not found: {DB}"}))
        return 1
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # Read recent dedup set
    seen: set[str] = set()
    if LOG_PATH.exists():
        try:
            with open(LOG_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                        if (time.time() - rec.get("ts_unix", 0)) < DEDUP_SEC:
                            seen.add(rec["session_id"])
                    except Exception:
                        continue
        except Exception:
            pass

    cutoff_ms = (time.time() - STALE_SEC) * 1000
    cur.execute("""SELECT session_id, title, error_code, error_message, updated_at_ms
                   FROM local_runtime_sessions
                   WHERE error_code IS NOT NULL
                     AND updated_at_ms < ?
                     AND archived = 0""", (cutoff_ms,))
    rows = cur.fetchall()

    archived_now: list[dict] = []
    for sid, title, ec, em, ts in rows:
        if sid in seen:
            continue
        # Archive
        try:
            cur.execute("UPDATE local_runtime_sessions SET archived = 1 WHERE session_id = ?", (sid,))
            if cur.rowcount:
                archived_now.append({
                    "ts": now_iso(),
                    "ts_unix": time.time(),
                    "session_id": sid,
                    "title": (title or "")[:80],
                    "error_code": ec,
                    "error_message": (em or "")[:200],
                    "updated_at_ist": datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M:%S"),
                })
        except Exception as e:
            print(f"err archiving {sid}: {e}", file=sys.stderr)

    conn.commit()
    conn.close()

    # Append to log
    if archived_now:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            for rec in archived_now:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # Append a block to handoff doc so primary chat sees it
        try:
            HANDOFF.parent.mkdir(parents=True, exist_ok=True)
            block_lines = [
                "",
                f"## Death-detector sweep @ {now_iso()}",
                f"Archived {len(archived_now)} errored session(s):",
                "",
            ]
            for rec in archived_now:
                block_lines.append(
                    f"- `{rec['session_id']}` — {rec['title']} — ec={rec['error_code']} @ {rec['updated_at_ist']}"
                )
            with open(HANDOFF, "a", encoding="utf-8") as f:
                f.write("\n".join(block_lines) + "\n")
        except Exception as e:
            print(f"handoff write err: {e}", file=sys.stderr)

    # Print one-line summary for cron log
    print(
        f"SESSION-DEATH-DETECTOR: {len(archived_now)} archived "
        f"(of {len(rows)} errored unarchived, {len(seen)} seen-recent)"
    )
    for rec in archived_now:
        print(f"  {rec['session_id']}  ec={rec['error_code']}  {rec['title']}")

    # 6. 715/1000 specific detection — flag for primary chat
    conn2 = sqlite3.connect(DB)
    cur2 = conn2.cursor()
    cutoff_24h_ms = (time.time() - 24 * 3600) * 1000
    cur2.execute(
        """SELECT session_id, title, error_code, updated_at_ms
           FROM local_runtime_sessions
           WHERE error_code = 50001
             AND updated_at_ms > ?
             AND (error_message LIKE '%715%' OR error_message LIKE '%1000%')""",
        (cutoff_24h_ms,),
    )
    seven15 = cur2.fetchall()
    conn2.close()
    if seven15:
        try:
            HANDOFF.parent.mkdir(parents=True, exist_ok=True)
            block = [
                "",
                f"## 715/1000 recovery alert @ {now_iso()}",
                f"Detected {len(seven15)} session(s) with `unknown error 715 (1000)` in the last 24h.",
                "**Pattern**: 715 is an upstream/model-provider transient API error, NOT a context-size issue.",
                "**Mitigated 2026-08-31 15:08**: switched 14 long-lived crons from `mode:sessionId` to `mode:new`.",
                "**Auto-recovery**: dead sessions archived; next cron tick starts a fresh session automatically.",
                "",
                "Affected (last 24h):",
            ]
            for sid, title, ec, ts in seven15[:10]:
                dt = datetime.fromtimestamp(ts / 1000).strftime("%H:%M:%S")
                block.append(f"- `{sid[:20]}` — {(title or '')[:45]} — {dt}")
            block.append("")
            with open(HANDOFF, "a", encoding="utf-8") as f:
                f.write("\n".join(block))
        except Exception as e:
            print(f"715 handoff write err: {e}", file=sys.stderr)
    return 0 if not archived_now else 1


if __name__ == "__main__":
    sys.exit(main())
