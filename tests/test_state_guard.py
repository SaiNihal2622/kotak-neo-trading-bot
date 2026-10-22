"""Tests for the system-level write-ownership guard (state_guard.py).

This is the STRUCTURAL fix for the recurring "two books fighting" class:
multiple components writing the same shared state file. The guard enforces
single-owner writes at the write site, so a rogue writer (bot, probe, harness,
reset script) CANNOT corrupt paper_state.json / quant_actions.json — it is
rejected fail-closed, no matter what.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from system.core.state_guard import guarded_write, OWNERS, READ_ONLY_COMPONENTS


def test_owner_map_is_single_owner(tmp_path):
    """Each shared file has exactly one owner."""
    assert OWNERS["paper_state.json"] == "ExecGateway"
    assert OWNERS["quant_actions.json"] == "Brain"
    assert OWNERS["quant_service_state.json"] == "Brain"


def test_gateway_can_write_paper_state(tmp_path):
    """The ExecGateway (rightful owner) can write paper_state.json."""
    f = tmp_path / "paper_state.json"
    ok, msg = guarded_write(f, {"cash": 100000, "positions": {}}, "ExecGateway")
    assert ok, msg
    assert json.loads(f.read_text(encoding="utf-8"))["cash"] == 100000


def test_probe_write_to_paper_state_is_rejected(tmp_path):
    """A probe/harness (read-only) is REJECTED from writing paper_state.json.

    This is the structural fix: a rogue probe or harness cannot clobber the
    gateway's real fills, even if it tries. Fail-closed.
    """
    f = tmp_path / "paper_state.json"
    f.write_text(json.dumps({"cash": 100000, "positions": {}}), encoding="utf-8")
    ok, msg = guarded_write(f, {"cash": 0, "positions": {}}, "Probe")
    assert not ok, "probe must be rejected"
    assert "read-only" in msg
    # The file is UNTOUCHED - the probe's empty book did not clobber it.
    assert json.loads(f.read_text(encoding="utf-8"))["cash"] == 100000


def test_probe_write_is_rejected(tmp_path):
    """Probes/harnesses are read-only and cannot write ANY shared file."""
    f = tmp_path / "quant_actions.json"
    ok, msg = guarded_write(f, {"actions": []}, "Probe")
    assert not ok
    assert "read-only" in msg


def test_brain_can_write_quant_actions(tmp_path):
    """The Brain (rightful owner) can write quant_actions.json."""
    f = tmp_path / "quant_actions.json"
    ok, msg = guarded_write(f, {"actions": [], "consumed": True}, "Brain")
    assert ok, msg


def test_unguarded_file_anyone_can_write(tmp_path):
    """Non-shared/scratch files are not guarded (any non-read-only can write)."""
    f = tmp_path / "scratch_note.json"
    ok, msg = guarded_write(f, {"x": 1}, "ExecGateway")
    assert ok, msg


def test_atomic_write_no_torn_read(tmp_path):
    """Atomic write leaves no .tmp residue and file is valid JSON."""
    f = tmp_path / "paper_state.json"
    ok, _ = guarded_write(f, {"cash": 50000}, "ExecGateway")
    assert ok
    assert not (tmp_path / "paper_state.json.tmp").exists()
    assert json.loads(f.read_text(encoding="utf-8"))["cash"] == 50000
