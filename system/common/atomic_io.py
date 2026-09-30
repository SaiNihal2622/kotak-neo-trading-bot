"""Atomic JSON IO helpers.

PHASE 6 FIX 2026-09-30: kills the intermittent `[Errno 22] Invalid argument`
on Windows when two writers (brain daemon + bridge) update the same
`data_cache/quant_actions.json` at the same instant. The pattern:

1. Write to `<file>.tmp` (with explicit fsync).
2. os.replace() atomically swaps the tmp into the real file. On Windows,
   os.replace is atomic at the OS level (MoveFileEx with REPLACE_EXISTING).
3. The real file's mtime updates even if a reader has it open — readers
   that already loaded the old contents keep them, new readers see the new.

This module also provides read_json() with utf-8-sig (BOM-safe) so callers
don't have to remember the BOM trap that already bit the bridge.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def read_json(path: Path | str, default: Any = None) -> Any:
    """Read a JSON file. utf-8-sig (BOM-safe). Returns default on error."""
    p = Path(path)
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError):
        return default


def write_json_atomic(path: Path | str, data: Any, *, ensure_ascii: bool = False) -> bool:
    """Write JSON atomically using a tmp + rename.

    Returns True on success, False on any IO error. The caller does NOT
    raise — atomic writes are best-effort, and a failed file write should
    not crash the main process. We log a warning at the caller.
    """
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        # Make sure parent dir exists
        p.parent.mkdir(parents=True, exist_ok=True)
        # Write to .tmp
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=ensure_ascii)
            f.flush()
            try:
                os.fsync(f.fileno())  # flush OS buffers before rename
            except (AttributeError, OSError):
                pass  # Windows doesn't always allow fsync; ignore
        # Atomic rename — Windows MoveFileEx with REPLACE_EXISTING
        os.replace(tmp, p)
        return True
    except Exception:
        # Cleanup tmp if it lingers
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return False


def write_text_atomic(path: Path | str, content: str) -> bool:
    """Atomic text write. Same pattern as write_json_atomic but for raw text."""
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except (AttributeError, OSError):
                pass
        os.replace(tmp, p)
        return True
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return False