"""Tests for the NSSM service-state self-heal recipe.

The NSSM service for KotakBotPaper went to Stopped state on 2026-09-07
00:42 IST (the bot process had SIGINT'd and NSSM gave up auto-restarting).
We added a new recipe that detects this and restarts the NSSM service
via the bot (which runs as SYSTEM and can call sc/NSSM without UAC).
"""
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kotak_bot import self_heal


def test_nssm_recipe_registered():
    """The NSSM recipe is registered in _NSSM_RECIPES (separate cooldown)."""
    assert "nssm_service_stopped" in self_heal._NSSM_RECIPES
    detect, fix = self_heal._NSSM_RECIPES["nssm_service_stopped"]
    assert detect == self_heal._detect_nssm_service_stopped
    assert fix == self_heal._fix_nssm_service_stopped


def test_nssm_cooldown_is_longer():
    """NSSM recipes use a longer cooldown than regular recipes."""
    assert self_heal.NSSM_COOLDOWN_SEC > self_heal.COOLDOWN_SEC
    assert self_heal.NSSM_COOLDOWN_SEC >= 1800  # at least 30 min


def test_detect_nssm_stopped_when_stopped():
    """Detector returns True when sc query shows STOPPED state."""
    fake_stdout = (
        "SERVICE_NAME: KotakBotPaper \n"
        "        TYPE               : 10  WIN32_OWN_PROCESS \n"
        "        STATE              : 1  STOPPED \n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_stdout, stderr="")
        assert self_heal._detect_nssm_service_stopped() is True


def test_detect_nssm_not_stopped_when_running():
    """Detector returns False when sc query shows RUNNING state."""
    fake_stdout = (
        "SERVICE_NAME: KotakBotPaper \n"
        "        STATE              : 4  RUNNING \n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_stdout, stderr="")
        assert self_heal._detect_nssm_service_stopped() is False


def test_detect_nssm_handles_subprocess_error():
    """Detector returns False if sc query fails (don't fire on error)."""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = Exception("sc not found")
        assert self_heal._detect_nssm_service_stopped() is False


def test_fix_nssm_calls_nssm_start():
    """Fix calls nssm start with the correct binary path."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="OK\n", stderr="",
        )
        result = self_heal._fix_nssm_service_stopped()
    assert result["applied"] is True
    # Verify the call was made to nssm.exe start KotakBotPaper
    args = mock_run.call_args[0][0]
    assert "nssm" in args[0].lower()
    assert "start" in args
    assert "KotakBotPaper" in args


def test_fix_nssm_handles_failure():
    """Fix returns applied=False if nssm fails."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="OpenService: Access is denied",
        )
        result = self_heal._fix_nssm_service_stopped()
    assert result["applied"] is False
    assert "Access is denied" in result["msg"]


def test_self_heal_check_uses_longer_cooldown_for_nssm():
    """The main check uses NSSM_COOLDOWN_SEC for NSSM recipes, COOLDOWN_SEC for others."""
    # Setup: pretend NSSM recipe fired 60s ago (within COOLDOWN but outside NSSM_COOLDOWN)
    import time
    self_heal._last_fired["nssm_service_stopped"] = time.time() - 60
    self_heal._last_fired["liveness_stale"] = time.time() - 60
    # The NSSM recipe should NOT fire (still in NSSM cooldown)
    # The regular recipe should NOT fire (still in regular cooldown)
    with patch.object(self_heal, "_detect_nssm_service_stopped", return_value=True), \
         patch.object(self_heal, "_fix_nssm_service_stopped", return_value={"applied": True, "msg": "ok", "action_for_telegram": "fixed"}), \
         patch.object(self_heal, "_detect_liveness_stale", return_value=True), \
         patch.object(self_heal, "_fix_liveness_stale", return_value={"applied": True, "msg": "ok", "action_for_telegram": "fixed"}), \
         patch.object(self_heal, "_read_tail", return_value=""):
        results = self_heal.self_heal_check({}, alerter=None)
    # Both should be in cooldown (fired 60s ago < 600s for regular, < 1800s for NSSM)
    assert not any(r["name"] == "nssm_service_stopped" for r in results)
    assert not any(r["name"] == "liveness_stale" for r in results)
    # Cleanup
    self_heal._last_fired.clear()
