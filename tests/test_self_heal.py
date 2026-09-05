"""Tests for the 24/7 autonomous self-heal engine.

The self-heal engine runs in the bot's main loop every 5 min and detects +
fixes known issues without human intervention. The user is often not at the
machine, especially during market hours.

Each recipe is tested for:
  - Detection works on a synthetic log/liveness
  - Fix applies (or escalates correctly if it can't)
  - Cooldown prevents re-firing within COOLDOWN_SEC
"""
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kotak_bot import self_heal as sh


def _liveness_fresh() -> dict:
    return {
        "ts": datetime.now(timezone(timedelta(hours=5, minutes=30))).isoformat(),
        "main_thread_alive": True,
        "tick": 100,
    }


def _liveness_stale() -> dict:
    return {
        "ts": (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat(),
        "main_thread_alive": True,
        "tick": 100,
    }


def _liveness_dead_thread() -> dict:
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "main_thread_alive": False,
        "tick": 100,
    }


def test_liveness_age_detection():
    """A liveness file older than 90s is 'stale' and triggers a bot restart."""
    age = sh._liveness_age_sec(_liveness_stale())
    assert age is not None
    assert age > 90, f"expected age > 90, got {age}"
    # Fresh liveness should not be stale
    assert sh._liveness_age_sec(_liveness_fresh()) < 10


def test_detect_liveness_stale():
    assert sh._detect_liveness_stale(_liveness_stale()) is True
    assert sh._detect_liveness_stale(_liveness_fresh()) is False


def test_detect_main_thread_dead():
    assert sh._detect_main_thread_dead(_liveness_dead_thread()) is True
    assert sh._detect_main_thread_dead(_liveness_fresh()) is False


def test_detect_shadow_import():
    assert sh._detect_shadow_import("foo bar\n[ERROR] cannot access local variable 'X'\n") is True
    assert sh._detect_shadow_import("all good here\n") is False


def test_detect_brain_loop_err():
    assert sh._detect_brain_loop_err("[2026-09-05 00:00] LOOP-ERR: foo") is True
    assert sh._detect_brain_loop_err("normal log line") is False


def test_detect_kotak_session_error():
    # URLError / getaddrinfo / session expired / auth failed all map to this
    for s in (
        "URLError: <urlopen error [Errno 11001] getaddrinfo failed>",
        "session expired at 14:00",
        "KotakProdFeed: auth failed: 401",
    ):
        assert sh._detect_kotak_session(s) is True, f"should detect: {s}"
    assert sh._detect_kotak_session("normal log line") is False


def test_self_heal_check_returns_list():
    """The check itself should not raise on a fresh liveness and clean log.
    We mock _read_tail to return empty so we don't get false positives from
    the real log files (which contain historical patterns from prior bugs).
    """
    sh._last_fired.clear()
    with patch.object(sh, "_read_tail", return_value=""):
        results = sh.self_heal_check(_liveness_fresh())
    assert isinstance(results, list)
    # With empty log + fresh liveness + live thread, expect 0 results
    assert results == [], f"expected no fixes on healthy system, got {results}"


def test_self_heal_fires_on_liveness_stale():
    """Stale liveness -> nssm restart. We mock _restart_bot_via_nssm so it
    doesn't actually try to restart anything during the test."""
    sh._last_fired.clear()
    mock_alerter = MagicMock()
    with patch("kotak_bot.self_heal._restart_bot_via_nssm", return_value=(True, "mocked restart ok")):
        results = sh.self_heal_check(_liveness_stale(), alerter=mock_alerter)
    # Should have fired liveness_stale
    names = [r["name"] for r in results]
    assert "liveness_stale" in names, f"expected liveness_stale in {names}"
    # The alerter should have been called (or not, depending on the recipe's
    # action_for_telegram presence)
    for r in results:
        if r.get("action_for_telegram"):
            assert mock_alerter.send.called


def test_self_heal_cooldown():
    """Same recipe shouldn't fire twice within COOLDOWN_SEC."""
    sh._last_fired.clear()
    with patch("kotak_bot.self_heal._restart_bot_via_nssm", return_value=(True, "ok")):
        r1 = sh.self_heal_check(_liveness_stale(), alerter=MagicMock())
    with patch("kotak_bot.self_heal._restart_bot_via_nssm", return_value=(True, "ok")):
        r2 = sh.self_heal_check(_liveness_stale(), alerter=MagicMock())
    # First call should fire; second should be in cooldown
    assert any(r["name"] == "liveness_stale" for r in r1)
    assert not any(r["name"] == "liveness_stale" for r in r2), \
        f"second call should be in cooldown, got: {r2}"


def test_self_heal_shadow_import_escalates():
    """Shadow import in log -> alert (no auto-fix available at runtime)."""
    sh._last_fired.clear()
    log = "[2026-09-05] cannot access local variable 'Order'"
    with patch.object(sh, "_read_tail", return_value=log):
        mock_alerter = MagicMock()
        results = sh.self_heal_check(_liveness_fresh(), alerter=mock_alerter)
    shadow_results = [r for r in results if r["name"] == "shadow_import_in_log"]
    assert len(shadow_results) == 1
    assert shadow_results[0]["applied"] is False, "shadow import can't be auto-fixed"
    # The alerter should have been called
    assert mock_alerter.send.called


def test_explain_summarizes_recipes():
    s = sh.explain()
    assert "self_heal" in s
    for name in sh.RECIPES:
        assert name in s, f"explain() missing recipe: {name}"


def test_no_shadow_imports_in_self_heal():
    """The new self_heal.py must not introduce any shadow-imports itself."""
    import subprocess
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "lint_no_shadowing.py")],
        capture_output=True, text=True, timeout=120,
    )
    assert "PASSED" in r.stdout, f"lint failed:\n{r.stdout}\n{r.stderr}"
