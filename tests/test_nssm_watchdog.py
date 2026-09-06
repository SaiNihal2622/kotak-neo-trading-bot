"""Tests for the NSSM watchdog script (3rd-layer watchdog)."""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Import the script as a module
sys.path.insert(0, str(ROOT / "scripts"))
import nssm_watchdog


def test_services_list():
    """Watchdog monitors both critical NSSM services."""
    assert "KotakBotPaper" in nssm_watchdog.SERVICES
    assert "KotakQuantService" in nssm_watchdog.SERVICES


def test_check_and_start_running():
    """If service is RUNNING, no action is taken."""
    fake_stdout = "STATE              : 4  RUNNING \n"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_stdout, stderr="")
        result = nssm_watchdog._check_and_start("KotakBotPaper", {})
    assert result["state_before"] == "RUNNING"
    assert result["started"] is False
    assert result["msg"] == "ok"


def test_check_and_start_stopped_starts():
    """If service is STOPPED, nssm start is called."""
    fake_sc = "STATE              : 1  STOPPED \n"
    fake_nssm = "Service started"
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=fake_sc, stderr=""),
            MagicMock(returncode=0, stdout=fake_nssm, stderr=""),
        ]
        # Mock telegram to avoid network calls
        with patch.object(nssm_watchdog, "_send_telegram", return_value=True):
            result = nssm_watchdog._check_and_start("KotakBotPaper", {})
    assert result["state_before"] == "STOPPED"
    assert result["started"] is True
    # Verify nssm was called
    assert any("start" in str(call.args) for call in mock_run.call_args_list)


def test_check_and_start_cooldown():
    """If alert was sent recently, don't re-send Telegram within cooldown."""
    import time
    fake_sc = "STATE              : 1  STOPPED \n"
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=fake_sc, stderr=""),
            MagicMock(returncode=0, stdout="started", stderr=""),
        ]
        with patch.object(nssm_watchdog, "_send_telegram") as mock_tg:
            # First call: state has recent alert (within cooldown)
            state = {"last_alert_ts": {"KotakBotPaper": time.time() - 60}}  # 60s ago
            nssm_watchdog._check_and_start("KotakBotPaper", state)
            # Telegram should NOT be called
            assert not mock_tg.called


def test_main_runs_clean():
    """main() returns 0 when both services are RUNNING."""
    fake_sc = "STATE              : 4  RUNNING \n"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_sc, stderr="")
        rc = nssm_watchdog.main()
    assert rc == 0


def test_main_returns_1_if_start_fails():
    """If a service fails to start, main() returns 1 (non-zero)."""
    fake_sc_stopped = "STATE              : 1  STOPPED \n"
    fake_sc_running = "STATE              : 4  RUNNING \n"
    with patch("subprocess.run") as mock_run:
        # First call: sc query for bot - STOPPED, second: nssm start fails,
        # third: sc query for brain - RUNNING
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=fake_sc_stopped, stderr=""),
            MagicMock(returncode=2, stdout="", stderr="Access denied"),
            MagicMock(returncode=0, stdout=fake_sc_running, stderr=""),
        ]
        with patch.object(nssm_watchdog, "_send_telegram", return_value=False):
            rc = nssm_watchdog.main()
    assert rc == 1
