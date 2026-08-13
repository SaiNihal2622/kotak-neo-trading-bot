"""Tests for the liveness_check.py watchdog script."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Ensure project root on path
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "liveness_check.py"), *args],
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={"PYTHONPATH": str(ROOT), "PATH": str(ROOT / ".venv" / "Scripts") + r";C:\Windows\system32;C:\Windows"},
    )


def test_missing_file_returns_dead(tmp_path: Path):
    missing = tmp_path / "nope.json"
    r = _run(["--ping-file", str(missing), "--json"], cwd=tmp_path)
    assert r.returncode == 1, r.stdout
    data = json.loads(r.stdout)
    assert data["alive"] is False
    assert data["reason"] == "liveness_file_missing"
    assert "liveness_file_missing" in r.stderr or r.stderr == ""


def test_fresh_file_returns_alive(tmp_path: Path):
    pf = tmp_path / "ping.json"
    pf.write_text(json.dumps({
        "ts": datetime.now().astimezone().isoformat(),
        "pid": 12345,
        "uptime_sec": 10.0,
        "tick": 5,
        "state": "running",
    }), encoding="utf-8")
    r = _run(["--ping-file", str(pf), "--json", "--max-age", "60"], cwd=tmp_path)
    assert r.returncode == 0, r.stdout
    data = json.loads(r.stdout)
    assert data["alive"] is True
    assert data["pid"] == 12345
    assert data["uptime_sec"] == 10.0


def test_stale_file_returns_dead(tmp_path: Path):
    pf = tmp_path / "ping.json"
    stale_ts = (datetime.now().astimezone() - timedelta(seconds=300)).isoformat()
    pf.write_text(json.dumps({
        "ts": stale_ts,
        "pid": 12345,
        "uptime_sec": 100.0,
        "state": "running",
    }), encoding="utf-8")
    r = _run(["--ping-file", str(pf), "--json", "--max-age", "60"], cwd=tmp_path)
    assert r.returncode == 1, r.stdout
    data = json.loads(r.stdout)
    assert data["alive"] is False
    assert "stale" in data["reason"]
    assert data["age_sec"] >= 290


def test_corrupt_file_returns_dead(tmp_path: Path):
    pf = tmp_path / "ping.json"
    pf.write_text("{not valid json", encoding="utf-8")
    r = _run(["--ping-file", str(pf), "--json", "--max-age", "60"], cwd=tmp_path)
    assert r.returncode == 1, r.stdout
    data = json.loads(r.stdout)
    assert data["alive"] is False
    assert "corrupt" in data["reason"]


def test_no_ts_returns_dead(tmp_path: Path):
    pf = tmp_path / "ping.json"
    pf.write_text(json.dumps({"pid": 1, "state": "running"}), encoding="utf-8")
    r = _run(["--ping-file", str(pf), "--json"], cwd=tmp_path)
    assert r.returncode == 1, r.stdout
    data = json.loads(r.stdout)
    assert data["alive"] is False
    assert data["reason"] == "liveness_file_no_ts"


def test_alive_includes_snapshot(tmp_path: Path):
    pf = tmp_path / "ping.json"
    pf.write_text(json.dumps({
        "ts": datetime.now().astimezone().isoformat(),
        "pid": 99,
        "uptime_sec": 5.0,
        "state": "running",
        "snapshot": {"capital": 100000, "vix": 11.42, "open_positions": 0},
    }), encoding="utf-8")
    r = _run(["--ping-file", str(pf), "--json", "--max-age", "60"], cwd=tmp_path)
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["snapshot"]["capital"] == 100000
    assert data["snapshot"]["vix"] == 11.42


def test_human_output_for_alive(tmp_path: Path):
    pf = tmp_path / "ping.json"
    pf.write_text(json.dumps({
        "ts": datetime.now().astimezone().isoformat(),
        "pid": 99,
        "uptime_sec": 5.0,
        "state": "running",
        "snapshot": {"capital": 132749.95, "realized_pnl": 5597.55, "open_positions": 4, "vix": 11.42},
    }), encoding="utf-8")
    r = _run(["--ping-file", str(pf), "--max-age", "60"], cwd=tmp_path)
    assert r.returncode == 0
    assert "✅" in r.stdout or "ALIVE" in r.stdout
    assert "132,749" in r.stdout or "132,750" in r.stdout or "132749" in r.stdout or "132750" in r.stdout


def test_human_output_for_dead(tmp_path: Path):
    pf = tmp_path / "ping.json"
    pf.write_text("not json at all", encoding="utf-8")
    r = _run(["--ping-file", str(pf), "--max-age", "60"], cwd=tmp_path)
    assert r.returncode == 1
    assert "DEAD" in r.stdout or "corrupt" in r.stdout or "missing" in r.stdout
