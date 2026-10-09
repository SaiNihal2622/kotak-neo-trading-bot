"""Tests for the hung-service watchdog.

NSSM auto-restarts a service that CRASHES but not one that is HUNG
(process alive, main loop stalled). hung_watchdog.py closes that gap by
checking liveness-file freshness and restarting stale services.

Run:
    .venv\\Scripts\\python.exe -m pytest tests/test_hung_watchdog.py -q
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')


@pytest.fixture()
def hw(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location('hw_ut', ROOT / 'scripts' / 'hung_watchdog.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    # Redirect log + data dir to a temp location so tests don't touch prod.
    m.LOG = tmp_path / 'hung_watchdog.log'
    m.DATA = tmp_path
    return m


def test_service_state_parses_running(hw, monkeypatch):
    """sc.exe 'STATE : 4  RUNNING' must parse to 'RUNNING'."""
    monkeypatch.setattr(hw.subprocess, 'run',
                        lambda *a, **k: _FakeProc('  STATE              : 4  RUNNING \r\n'))
    assert hw._service_state('KotakBotPaper') == 'RUNNING'


def test_service_state_parses_paused(hw, monkeypatch):
    monkeypatch.setattr(hw.subprocess, 'run',
                        lambda *a, **k: _FakeProc('  STATE              : 7  PAUSED \r\n'))
    assert hw._service_state('KotakBotPaper') == 'PAUSED'


def test_file_age_missing_is_infinite(hw):
    assert hw._file_age_sec(hw.DATA / 'nope.json') == float('inf')


def test_file_age_fresh(hw):
    p = hw.DATA / 'fresh.json'
    p.write_text('{}')
    assert hw._file_age_sec(p) < 5


def test_healthy_service_not_restarted(hw, monkeypatch):
    """Fresh liveness + RUNNING => no restart."""
    (hw.DATA / 'liveness.json').write_text('{}')
    (hw.DATA / 'quant_service_state.json').write_text('{}')
    restarted = []
    monkeypatch.setattr(hw, '_service_state', lambda s: 'RUNNING')
    monkeypatch.setattr(hw, '_restart', lambda s: restarted.append(s))
    hw.main()
    assert restarted == []


def test_stale_service_restarted(hw, monkeypatch):
    """Stale liveness + RUNNING => restart."""
    import os, time
    for name in ('liveness.json', 'quant_service_state.json'):
        p = hw.DATA / name
        p.write_text('{}')
        old = time.time() - 10000
        os.utime(p, (old, old))
    restarted = []
    monkeypatch.setattr(hw, '_service_state', lambda s: 'RUNNING')
    monkeypatch.setattr(hw, '_restart', lambda s: restarted.append(s))
    hw.main()
    assert 'KotakBotPaper' in restarted


def test_not_running_service_skipped(hw, monkeypatch):
    """A service that is STOPPED is NSSM's job, not the hung watchdog's."""
    (hw.DATA / 'liveness.json').write_text('{}')
    (hw.DATA / 'quant_service_state.json').write_text('{}')
    restarted = []
    monkeypatch.setattr(hw, '_service_state', lambda s: 'STOPPED')
    monkeypatch.setattr(hw, '_restart', lambda s: restarted.append(s))
    hw.main()
    assert restarted == []


class _FakeProc:
    def __init__(self, stdout):
        self.stdout = stdout
