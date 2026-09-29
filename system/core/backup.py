"""Backup script for production deployments.

Copies the SQLite event store to a timestamped backup directory.
Keeps the last 30 backups; rotates older ones.

Usage:
  python -m system.core.backup [--db data/state.db] [--dest backups/]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data_cache/state.db")
    parser.add_argument("--dest", default="backups/")
    parser.add_argument("--keep", type=int, default=30)
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"DB not found: {db_path}")
        sys.exit(1)

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    target = dest / f"state-{ts}.db"
    shutil.copy2(db_path, target)

    # Also copy -wal and -shm if present
    for suffix in ("-wal", "-shm"):
        src = db_path.with_name(db_path.name + suffix)
        if src.exists():
            shutil.copy2(src, dest / f"state-{ts}.db{suffix}")

    # Rotate: keep last N
    backups = sorted(dest.glob("state-*.db*"))
    if len(backups) > args.keep * 3:  # *.db, *.db-wal, *.db-shm = 3 per backup
        to_delete = backups[: len(backups) - args.keep * 3]
        for f in to_delete:
            f.unlink()
            print(f"rotated old backup: {f.name}")

    print(f"backup created: {target}")
    print(f"size: {target.stat().st_size / 1024:.1f} KB")
    print(f"backups kept: {args.keep}")


if __name__ == "__main__":
    main()