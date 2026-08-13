"""Tests for the liveness monitor + crash reporting."""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from kotak_bot.utils.liveness import LivenessMonitor, install_default


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------- basic lifecycle ----------

def test_liveness_starts_and_writes_ping(tmp_path: Path):
    mon = LivenessMonitor(
        ping_file=str(tmp_path / "ping.json"),
        crash_file=str(tmp_path / "crash.jsonl"),
        interval_sec=1.0,  # min allowed; thread sleeps 1s before first 'running' ping
    )
    mon.start()
    # First ping is written synchronously in start() with state="starting"
    # before the thread is launched
    assert mon.ping_file.exists()
    first = _read_json(mon.ping_file)
    assert first["state"] == "starting"
    assert first["pid"] == os.getpid()
    assert "ts" in first
    # Now wait for the thread to take over (interval_sec + buffer)
    deadline = time.time() + 3.0
    while time.time() < deadline:
        d = _read_json(mon.ping_file)
        if d["state"] == "running":
            break
        time.sleep(0.1)
    second = _read_json(mon.ping_file)
    assert second["state"] == "running", f"expected running, got {second}"
    assert second["tick"] >= 1
    mon.stop()


def test_liveness_stop_writes_crash_event(tmp_path: Path):
    crash = tmp_path / "crash.jsonl"
    mon = LivenessMonitor(
        ping_file=str(tmp_path / "ping.json"),
        crash_file=str(crash),
        interval_sec=1.0,
    )
    mon.start()
    time.sleep(0.2)
    mon.stop(reason="unit_test_stop")
    events = _read_jsonl(crash)
    assert any(e.get("event") == "stop" and e.get("reason") == "unit_test_stop" for e in events), events


def test_register_exit_writes_event(tmp_path: Path):
    crash = tmp_path / "crash.jsonl"
    mon = LivenessMonitor(
        ping_file=str(tmp_path / "ping.json"),
        crash_file=str(crash),
        interval_sec=1.0,
    )
    mon.start()
    mon.register_exit("manual_exit", extra={"context": "test"})
    events = _read_jsonl(crash)
    assert any(e.get("event") == "exit" and e.get("reason") == "manual_exit" for e in events)
    assert any(e.get("event") == "exit" and e.get("extra", {}).get("context") == "test" for e in events)
    mon.stop()


def test_state_provider_called(tmp_path: Path):
    counter = {"n": 0}

    def provider() -> dict:
        counter["n"] += 1
        return {"foo": "bar", "n": counter["n"]}

    mon = LivenessMonitor(
        ping_file=str(tmp_path / "ping.json"),
        crash_file=str(tmp_path / "crash.jsonl"),
        interval_sec=1.0,
        state_provider=provider,
    )
    mon.start()
    # Wait for at least 2 ticks (initial sleep + first running ping + second ping)
    deadline = time.time() + 5.0
    while time.time() < deadline and counter["n"] < 2:
        time.sleep(0.2)
    # Read with retry to avoid catching the file mid-rename
    payload = None
    for _ in range(5):
        try:
            payload = _read_json(mon.ping_file)
            if payload.get("state") == "running":
                break
        except (json.JSONDecodeError, FileNotFoundError):
            pass
        time.sleep(0.1)
    assert payload is not None, "ping file never valid"
    assert payload["snapshot"]["foo"] == "bar"
    assert counter["n"] >= 1
    mon.stop()


def test_provider_exception_does_not_kill_thread(tmp_path: Path):
    """Provider errors are absorbed into the snapshot as provider_error;
    the liveness thread must keep running and the ping file must stay valid."""
    def bad_provider() -> dict:
        raise RuntimeError("boom")

    mon = LivenessMonitor(
        ping_file=str(tmp_path / "ping.json"),
        crash_file=str(tmp_path / "crash.jsonl"),
        interval_sec=1.0,
        state_provider=bad_provider,
    )
    mon.start()
    # Wait for at least 2 ticks
    deadline = time.time() + 5.0
    while time.time() < deadline:
        d = _read_json(mon.ping_file)
        if d.get("state") == "running":
            break
        time.sleep(0.2)
    # Thread must still be running
    assert mon._thread.is_alive()  # type: ignore[union-attr]
    # Ping file should still be valid JSON, and the error should be recorded
    # inside the snapshot rather than killing the thread
    payload = _read_json(mon.ping_file)
    assert "snapshot" in payload
    assert "provider_error" in payload["snapshot"]
    assert "boom" in payload["snapshot"]["provider_error"]
    # tick should have advanced (proves the thread is still iterating)
    assert payload["tick"] >= 1
    mon.stop()


def test_is_alive_uses_last_ping_ts(tmp_path: Path):
    mon = LivenessMonitor(
        ping_file=str(tmp_path / "ping.json"),
        crash_file=str(tmp_path / "crash.jsonl"),
        interval_sec=0.1,
    )
    mon.start()
    time.sleep(0.3)
    assert mon.is_alive()
    assert mon.last_ping_age_sec() is not None
    assert mon.last_ping_age_sec() < 2.0  # type: ignore[operator]
    mon.stop()


def test_idempotent_start(tmp_path: Path):
    mon = LivenessMonitor(
        ping_file=str(tmp_path / "ping.json"),
        crash_file=str(tmp_path / "crash.jsonl"),
        interval_sec=0.2,
    )
    mon.start()
    t1 = mon._thread  # type: ignore[union-attr]
    mon.start()  # second call should be a no-op
    t2 = mon._thread  # type: ignore[union-attr]
    assert t1 is t2
    mon.stop()


def test_atexit_fires_on_clean_shutdown(tmp_path: Path):
    """When the interpreter exits cleanly, atexit handler should write a crash event.

    We can't easily test the real atexit firing without exiting the test
    process, so we invoke the handler directly here (it's installed by .start()).
    """
    crash = tmp_path / "crash.jsonl"
    mon = LivenessMonitor(
        ping_file=str(tmp_path / "ping.json"),
        crash_file=str(crash),
        interval_sec=0.2,
    )
    mon.start()
    # Manually invoke the atexit handler (simulates interpreter shutdown)
    mon._on_atexit()  # type: ignore[attr-defined]
    events = _read_jsonl(crash)
    assert any(e.get("event") == "atexit" for e in events), events
    mon.stop()


def test_signal_handler_writes_event(tmp_path: Path):
    """Direct unit test: invoke the SIGTERM-style handler and verify it writes an event."""
    crash = tmp_path / "crash.jsonl"
    mon = LivenessMonitor(
        ping_file=str(tmp_path / "ping.json"),
        crash_file=str(crash),
        interval_sec=0.2,
    )
    mon.start()
    handler = mon._make_signal_handler("SIGTERM_TEST")  # type: ignore[attr-defined]
    try:
        handler(signal.SIGTERM, None)
    except SystemExit:
        pass  # expected — handler calls sys.exit
    events = _read_jsonl(crash)
    assert any(e.get("event") == "signal" and e.get("reason") == "SIGTERM_TEST" for e in events), events
    # don't call mon.stop() — atexit hook should have fired, and signal handler
    # also set the exit reason


def test_ping_file_atomic_rewrite(tmp_path: Path):
    """Verify ping file is always valid JSON even if read mid-rewrite."""
    mon = LivenessMonitor(
        ping_file=str(tmp_path / "ping.json"),
        crash_file=str(tmp_path / "crash.jsonl"),
        interval_sec=0.1,
    )
    mon.start()
    for _ in range(20):
        time.sleep(0.05)
        if mon.ping_file.exists():
            # File should always be valid JSON (atomic rename)
            data = _read_json(mon.ping_file)
            assert "ts" in data
    mon.stop()


def test_install_default_singleton(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Reset module-level singleton first
    import kotak_bot.utils.liveness as lm
    monkeypatch.setattr(lm, "_DEFAULT", None)
    m1 = install_default(
        ping_file=str(tmp_path / "p.json"),
        crash_file=str(tmp_path / "c.jsonl"),
        interval_sec=0.2,
    )
    m2 = install_default()  # second call returns same instance
    assert m1 is m2
    m1.stop()


def test_crash_event_has_required_fields(tmp_path: Path):
    crash = tmp_path / "crash.jsonl"
    mon = LivenessMonitor(
        ping_file=str(tmp_path / "ping.json"),
        crash_file=str(crash),
        interval_sec=0.2,
    )
    mon.start()
    mon.register_exit("field_check", extra={"k": "v"})
    events = _read_jsonl(crash)
    e = next(e for e in events if e.get("reason") == "field_check")
    for field in ("ts", "event", "reason", "uptime_sec", "pid", "python_version", "platform"):
        assert field in e, f"missing {field}: {e}"
    assert e["event"] == "exit"
    assert e["pid"] == os.getpid()
    assert e["extra"] == {"k": "v"}
    mon.stop()
