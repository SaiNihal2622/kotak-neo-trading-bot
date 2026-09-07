"""Tests for preflight_check.py — the 24/7 reliability gate.

Verifies the structure of checks: each check returns a Check object with
the right fields, and the report builder produces a valid Telegram-friendly
message. We don't actually run sc query / nssm in tests (those need a real
Windows service environment), but we exercise the parsing logic.
"""
import sys
import json
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the preflight module
import scripts.preflight_check as pf


@pytest.fixture
def tmp_dcache(tmp_path, monkeypatch):
    """Set up an isolated data_cache for the test."""
    dcache = tmp_path / "data_cache"
    dcache.mkdir()
    monkeypatch.setattr(pf, "DCACHE", dcache)
    return dcache


def test_check_dataclass_basics():
    c = pf.Check("test", "error")
    assert c.name == "test"
    assert c.severity == "error"
    assert not c.passed
    assert c.message == ""
    assert not c.fix_applied
    assert c.fix_message == ""
    s = repr(c)
    assert "test" in s


def test_check_repr_passing():
    c = pf.Check("foo", "warning")
    c.passed = True
    c.message = "all good"
    s = repr(c)
    assert "OK" in s
    assert "foo" in s
    assert "all good" in s


def test_check_repr_failing():
    c = pf.Check("bar", "error")
    c.message = "broken"
    s = repr(c)
    assert "FAIL" in s
    assert "broken" in s
    assert "error" in s


def test_check_repr_with_fix():
    c = pf.Check("baz", "warning")
    c.fix_applied = True
    c.fix_message = "auto-restarted"
    c.message = "was down"
    s = repr(c)
    assert "auto-fix" in s
    assert "auto-restarted" in s


def test_check_inline_journal_no_file(tmp_dcache):
    """No trade_journal.jsonl -> not passed."""
    c = pf._check_inline_journal_callback()
    assert c.message == "trade_journal.jsonl missing"


def test_check_inline_journal_with_entries(tmp_dcache):
    """trade_journal.jsonl with FILL entries -> passed."""
    journal = tmp_dcache / "trade_journal.jsonl"
    journal.write_text(
        '{"trade_id":"FILL-X","ts":"2026-09-08T12:00:00"}\n', encoding="utf-8"
    )
    c = pf._check_inline_journal_callback()
    assert c.passed
    assert "FILL" in c.message


def test_check_inline_journal_after_hours_warning(tmp_dcache):
    """After-hours with 0 entries is a warning."""
    journal = tmp_dcache / "trade_journal.jsonl"
    journal.write_text("", encoding="utf-8")
    c = pf._check_inline_journal_callback()
    # The severity is determined by current time. If running during 9:15-15:30
    # it's an error; otherwise warning. Just verify the message mentions after-hours
    # or market hours.
    assert "after-hours" in c.message or "market hours" in c.message


def test_check_daily_json_today(tmp_dcache):
    """daily.json with today's date -> passed."""
    perf = tmp_dcache / "performance" / "daily.json"
    perf.parent.mkdir(parents=True, exist_ok=True)
    perf.write_text(
        json.dumps({"date": "2026-09-08", "last_updated": "2026-09-08T15:30:00"}),
        encoding="utf-8",
    )
    c = pf._check_daily_json()
    assert c.passed


def test_check_daily_json_missing(tmp_dcache):
    """daily.json missing -> not passed."""
    c = pf._check_daily_json()
    assert not c.passed
    assert c.message == "missing"


def test_check_no_stale_force_action_consumed(tmp_dcache):
    """consumed=True is healthy."""
    fa = tmp_dcache / "mavis_force_action.json"
    fa.write_text(json.dumps({"action": "RUN_COMMAND", "consumed": True}), encoding="utf-8")
    c = pf._check_no_stale_force_action()
    assert c.passed
    assert "consumed=True" in c.message


def test_check_no_stale_force_action_unconsumed(tmp_dcache):
    """Unconsumed is a warning."""
    fa = tmp_dcache / "mavis_force_action.json"
    fa.write_text(
        json.dumps({"action": "RUN_COMMAND", "consumed": False, "ts": "2026-09-08T01:00:00"}),
        encoding="utf-8",
    )
    c = pf._check_no_stale_force_action()
    assert not c.passed
    assert "unconsumed" in c.message
    assert c.severity == "warning"


def test_check_no_stale_force_action_missing(tmp_dcache):
    """No file is healthy."""
    c = pf._check_no_stale_force_action()
    assert c.passed
    assert "no force-action" in c.message


def test_check_no_crash_today_empty(tmp_dcache):
    """No crash log file is healthy."""
    c = pf._check_no_crash_today()
    assert c.passed
    assert "no crash log" in c.message


def test_check_no_crash_today_clean(tmp_dcache):
    """Crash log with no entries from today is healthy."""
    crash = tmp_dcache / "liveness_crash.jsonl"
    crash.write_text('{"ts":"2026-09-05T10:00:00"}\n', encoding="utf-8")
    c = pf._check_no_crash_today()
    assert c.passed
    assert "0 crashes" in c.message


def test_check_kotak_session_missing(tmp_dcache):
    c = pf._check_kotak_session()
    assert not c.passed
    assert "missing" in c.message


def test_check_kotak_session_valid(tmp_dcache):
    """Session valid for >2h -> passed."""
    import time
    sess = tmp_dcache / "kotak_prod_session.json"
    sess.write_text(json.dumps({"expires_at": time.time() + 3600 * 5}), encoding="utf-8")
    c = pf._check_kotak_session()
    assert c.passed
    assert "h left" in c.message


def test_check_kotak_session_expiring(tmp_dcache):
    """Session with <2h left is a warning."""
    import time
    sess = tmp_dcache / "kotak_prod_session.json"
    sess.write_text(json.dumps({"expires_at": time.time() + 600}), encoding="utf-8")
    c = pf._check_kotak_session()
    assert not c.passed
    assert "re-auth needed" in c.message
    assert c.severity == "warning"


def test_check_inline_journal_filters_by_today(tmp_dcache):
    """Only today's FILL entries are counted."""
    journal = tmp_dcache / "trade_journal.jsonl"
    journal.write_text(
        '{"trade_id":"FILL-OLD","ts":"2026-09-01T10:00:00"}\n'
        '{"trade_id":"FILL-NEW","ts":"2026-09-08T10:00:00"}\n',
        encoding="utf-8",
    )
    c = pf._check_inline_journal_callback()
    # Should pass (1 entry today) regardless of time
    assert c.passed
    assert "1 inline FILL" in c.message


def test_main_exit_0_all_pass(tmp_dcache):
    """All checks pass -> exit 0."""
    def passing_check():
        c = pf.Check("test", "error")
        c.passed = True
        c.message = "ok"
        return c
    with patch.object(pf, "_check_bot_process", passing_check), \
         patch.object(pf, "_check_brain", passing_check), \
         patch.object(pf, "_check_nssm_botpaper", passing_check), \
         patch.object(pf, "_check_nssm_quantservice", passing_check), \
         patch.object(pf, "_check_no_duplicate_bots", passing_check), \
         patch.object(pf, "_check_bot_code_current", passing_check), \
         patch.object(pf, "_check_inline_journal_callback", passing_check), \
         patch.object(pf, "_check_daily_json", passing_check), \
         patch.object(pf, "_check_scheduled_tasks", passing_check), \
         patch.object(pf, "_check_no_stale_force_action", passing_check), \
         patch.object(pf, "_check_no_crash_today", passing_check), \
         patch.object(pf, "_check_kotak_session", passing_check), \
         patch.object(pf, "_check_self_heal_recipes", passing_check), \
         patch.object(pf, "_send_telegram", return_value=False):
        rc = pf.main()
        assert rc == 0


def test_main_exit_1_with_autofix(tmp_dcache):
    """Some checks pass with auto-fix applied -> exit 1."""
    def passing_check():
        c = pf.Check("test", "error")
        c.passed = True
        c.message = "ok"
        return c
    def autofixed_check():
        c = pf.Check("fix", "error")
        c.passed = True
        c.fix_applied = True
        c.message = "was broken, fixed"
        return c
    with patch.object(pf, "_check_bot_process", autofixed_check), \
         patch.object(pf, "_check_brain", passing_check), \
         patch.object(pf, "_check_nssm_botpaper", passing_check), \
         patch.object(pf, "_check_nssm_quantservice", passing_check), \
         patch.object(pf, "_check_no_duplicate_bots", passing_check), \
         patch.object(pf, "_check_bot_code_current", passing_check), \
         patch.object(pf, "_check_inline_journal_callback", passing_check), \
         patch.object(pf, "_check_daily_json", passing_check), \
         patch.object(pf, "_check_scheduled_tasks", passing_check), \
         patch.object(pf, "_check_no_stale_force_action", passing_check), \
         patch.object(pf, "_check_no_crash_today", passing_check), \
         patch.object(pf, "_check_kotak_session", passing_check), \
         patch.object(pf, "_check_self_heal_recipes", passing_check), \
         patch.object(pf, "_send_telegram", return_value=False):
        rc = pf.main()
        assert rc == 1


def test_main_exit_2_critical_failure(tmp_dcache):
    """Critical failure -> exit 2."""
    def passing_check():
        c = pf.Check("test", "error")
        c.passed = True
        c.message = "ok"
        return c
    def critical_failure():
        c = pf.Check("crit", "error")
        c.message = "broken"
        return c
    with patch.object(pf, "_check_bot_process", critical_failure), \
         patch.object(pf, "_check_brain", passing_check), \
         patch.object(pf, "_check_nssm_botpaper", passing_check), \
         patch.object(pf, "_check_nssm_quantservice", passing_check), \
         patch.object(pf, "_check_no_duplicate_bots", passing_check), \
         patch.object(pf, "_check_bot_code_current", passing_check), \
         patch.object(pf, "_check_inline_journal_callback", passing_check), \
         patch.object(pf, "_check_daily_json", passing_check), \
         patch.object(pf, "_check_scheduled_tasks", passing_check), \
         patch.object(pf, "_check_no_stale_force_action", passing_check), \
         patch.object(pf, "_check_no_crash_today", passing_check), \
         patch.object(pf, "_check_kotak_session", passing_check), \
         patch.object(pf, "_check_self_heal_recipes", passing_check), \
         patch.object(pf, "_send_telegram", return_value=False):
        rc = pf.main()
        assert rc == 2
