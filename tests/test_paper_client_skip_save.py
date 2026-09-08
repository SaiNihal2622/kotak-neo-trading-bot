"""Tests for the skip-save flag in PaperClient._save_state (commit adding flag).

BUG HISTORY (2026-09-08):
The pre-market reset script writes a clean paper_state.json, but the bot's
in-process _save_state runs on every tick (~every 2-5s). The bot's in-memory
state was overwriting the clean reset within seconds, so the reset was lost
even though the file briefly looked correct.

FIX 2026-09-08 14:20: skip-save flag at data_cache/_skip_save.json. While
the flag is present, _save_state returns early (no write). The flag is
auto-removed by PaperClient.__init__ once a new process loads the clean
state, so it doesn't persist beyond the reset window. A 60s safety
expiry also prevents indefinite blocking if no one removes the flag.

These tests verify the flag pattern works correctly:
  1. _save_state skips when flag is present (file unchanged)
  2. _save_state runs normally when flag is absent
  3. Flag is auto-removed by PaperClient.__init__ on startup
  4. Stale flag (older than 60s) is removed and _save_state proceeds
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _make_paper_client(tmp_path: Path, **kwargs):
    """Helper: build a PaperClient with a temp persist_path."""
    from kotak_bot.broker.paper_client import PaperClient
    persist = str(tmp_path / "paper_state.json")
    defaults = dict(
        starting_capital=100_000.0,
        persist_path=persist,
    )
    defaults.update(kwargs)
    return PaperClient(**defaults)


def test_save_state_skipped_when_flag_present(tmp_path: Path):
    """When _skip_save.json exists, _save_state must NOT touch paper_state.json."""
    pc = _make_paper_client(tmp_path)
    skip_flag = tmp_path / "_skip_save.json"
    skip_flag.write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reason": "test",
    }), encoding="utf-8")
    # Write a known paper_state.json
    pc.persist_path.write_text(json.dumps({
        "cash": 99_999.0,
        "realized_pnl": 1234.5,
        "orders": {},
        "positions": {},
    }), encoding="utf-8")
    # Modify in-memory state
    pc._cash = 50_000.0
    pc._realized_pnl = 0.0
    # Call _save_state — should be a no-op because flag is present
    pc._save_state()
    # paper_state.json should be UNCHANGED
    state = json.loads(pc.persist_path.read_text(encoding="utf-8"))
    assert state["cash"] == 99_999.0
    assert state["realized_pnl"] == 1234.5


def test_save_state_runs_when_flag_absent(tmp_path: Path):
    """When _skip_save.json is absent, _save_state must write the in-memory state."""
    pc = _make_paper_client(tmp_path)
    # Ensure no flag
    skip_flag = tmp_path / "_skip_save.json"
    if skip_flag.exists():
        skip_flag.unlink()
    # Modify in-memory state
    pc._cash = 77_777.0
    pc._realized_pnl = -500.0
    # Call _save_state — should write
    pc._save_state()
    state = json.loads(pc.persist_path.read_text(encoding="utf-8"))
    assert state["cash"] == 77_777.0
    assert state["realized_pnl"] == -500.0


def test_flag_removed_by_init_on_startup(tmp_path: Path):
    """PaperClient.__init__ must remove the skip-save flag after loading state."""
    # Pre-create the flag (simulating the reset script's state)
    skip_flag = tmp_path / "_skip_save.json"
    skip_flag.write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reason": "test",
    }), encoding="utf-8")
    assert skip_flag.exists()
    # Build PaperClient — __init__ should remove the flag
    pc = _make_paper_client(tmp_path)
    assert not skip_flag.exists(), (
        f"PaperClient.__init__ did not remove the skip-save flag — "
        f"the new bot would never save state and lose track of new trades"
    )


def test_stale_flag_is_removed_by_save_state(tmp_path: Path):
    """A flag older than 60s must be auto-removed by _save_state, not honored forever."""
    pc = _make_paper_client(tmp_path)
    skip_flag = tmp_path / "_skip_save.json"
    # Backdate the flag by 65 seconds
    skip_flag.write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reason": "test-stale",
    }), encoding="utf-8")
    import os
    backdate = time.time() - 65
    os.utime(skip_flag, (backdate, backdate))
    # Modify in-memory state
    pc._cash = 33_333.0
    pc._realized_pnl = 100.0
    # Call _save_state — should remove stale flag and write
    pc._save_state()
    assert not skip_flag.exists(), "stale flag must be removed by _save_state"
    state = json.loads(pc.persist_path.read_text(encoding="utf-8"))
    assert state["cash"] == 33_333.0
    assert state["realized_pnl"] == 100.0


def test_flag_with_fresh_mtime_is_honored(tmp_path: Path):
    """A flag with current mtime must be honored (within the 60s window)."""
    pc = _make_paper_client(tmp_path)
    skip_flag = tmp_path / "_skip_save.json"
    skip_flag.write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reason": "test-fresh",
    }), encoding="utf-8")
    # Write a known paper_state.json
    pc.persist_path.write_text(json.dumps({
        "cash": 88_888.0,
        "realized_pnl": -100.0,
        "orders": {},
        "positions": {},
    }), encoding="utf-8")
    # Modify in-memory state
    pc._cash = 50_000.0
    # Flag is fresh (just created), so _save_state should be no-op
    pc._save_state()
    state = json.loads(pc.persist_path.read_text(encoding="utf-8"))
    assert state["cash"] == 88_888.0, (
        f"fresh flag should be honored — paper_state.json should be unchanged"
    )
