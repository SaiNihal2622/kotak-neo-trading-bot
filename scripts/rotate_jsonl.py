"""mavis_actions.jsonl rotation — caps the file at MAX_BYTES, rotates older entries.

Background: mavis_actions.jsonl grows by ~700KB/day from cron writes. After 30
days it'd be 21MB, slowing every read. The 2026-08-30 self-driver note flagged
this as P3.

Run nightly via kotak-nightly-improvement at 23:00 IST.
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache')
TARGETS = [
    DATA_DIR / 'mavis_actions.jsonl',
    DATA_DIR / 'mavis_events.jsonl',
    DATA_DIR / 'self_audit.jsonl',
    DATA_DIR / 'http_watchdog.jsonl',
    DATA_DIR / 'reconcile.jsonl',
    DATA_DIR / 'heartbeat_history.jsonl',
    DATA_DIR / 'session_death_detector.jsonl',
    DATA_DIR / 'session_715_recovery.jsonl',
    DATA_DIR / 'thesis_history.jsonl',
]
MAX_BYTES = 500 * 1024  # 500KB per file


def rotate(path: Path) -> dict:
    """If path is larger than MAX_BYTES, keep the tail and rotate the head."""
    if not path.exists():
        return {"file": path.name, "status": "missing"}
    size = path.stat().st_size
    if size <= MAX_BYTES:
        return {"file": path.name, "size_kb": size // 1024, "status": "ok"}

    # Read all lines, keep last N that fit in MAX_BYTES
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception as e:
        return {"file": path.name, "error": str(e)[:100]}

    # Walk from end, keep adding until we hit the limit
    kept: list[str] = []
    bytes_kept = 0
    for line in reversed(lines):
        line_bytes = len(line.encode('utf-8'))
        if bytes_kept + line_bytes > MAX_BYTES and kept:
            break
        kept.append(line)
        bytes_kept += line_bytes
    kept.reverse()

    # Write to .1 (rotated archive)
    archive = path.with_suffix(path.suffix + '.1')
    try:
        if archive.exists():
            archive.unlink()
        path.rename(archive)
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(kept)
    except Exception as e:
        return {"file": path.name, "error": str(e)[:100]}

    return {
        "file": path.name,
        "old_size_kb": size // 1024,
        "new_size_kb": bytes_kept // 1024,
        "lines_kept": len(kept),
        "lines_dropped": len(lines) - len(kept),
        "status": "rotated",
    }


def main() -> int:
    rotated = []
    for p in TARGETS:
        r = rotate(p)
        if r.get("status") in ("rotated", "ok", "missing"):
            print(f"  {r.get('file','?')}: {r.get('status')} ({r.get('size_kb', r.get('new_size_kb', '?'))}KB)")
        else:
            print(f"  {r.get('file','?')}: ERROR {r.get('error','?')}")
        if r.get("status") == "rotated":
            rotated.append(r)
    print()
    print(f"ROTATE-JSONL: {len(rotated)} file(s) rotated")
    return 0 if not rotated else 1


if __name__ == "__main__":
    sys.exit(main())
