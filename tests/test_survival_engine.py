"""Tests for the survival engine ("earn or die" layer).

The brain is fully autonomous and self-learning. Without a survival layer
it can keep trading after a drawdown and blow up the account. This module
makes "stay alive" a hard, deterministic constraint the LLM cannot
override.

Run:
    .venv\\Scripts\\python.exe -m pytest tests/test_survival_engine.py -q
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')


@pytest.fixture()
def se(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location('se_ut', ROOT / 'scripts' / 'survival_engine.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    # Redirect state to a temp file so tests don't touch prod.
    m.STATE_PATH = tmp_path / 'survival_state.json'
    m.DATA = tmp_path
    return m


def test_initial_state(se):
    st = se.snapshot()
    assert st['policy']['kill_switch'] is False
    assert st['banked'] == 0.0


def test_profit_banked_60_percent(se):
    """40/60 split: 60% of realized profit is banked, 40% redeployable."""
    st = se.update(realized_pnl=10_000.0, cash=100_000.0)
    assert st['banked'] == pytest.approx(6_000.0)   # 60% banked
    assert st['deployable'] == pytest.approx(104_000.0)  # 100k + 40% of 10k


def test_no_profit_no_banking(se):
    st = se.update(realized_pnl=-5_000.0, cash=95_000.0)
    assert st['banked'] == 0.0
    # Losses reduce deployable by the same 40% ratio: 100k + (-5k)*0.4 = 98k.
    assert st['deployable'] == pytest.approx(98_000.0)


def test_survival_mode_when_equity_below_floor(se):
    """Equity < 50% of start => survival_mode, no new positions."""
    st = se.update(realized_pnl=-60_000.0, cash=40_000.0)
    assert st['survival_mode'] is True
    gate = se.can_open_position(cash=40_000.0, realized=-60_000.0)
    assert gate['allowed'] is False
    assert 'SURVIVAL' in gate['reason']


def test_normal_mode_allows_positions(se):
    st = se.update(realized_pnl=5_000.0, cash=105_000.0)
    assert st['survival_mode'] is False
    gate = se.can_open_position(cash=105_000.0, realized=5_000.0)
    assert gate['allowed'] is True


def test_kill_switch_blocks_positions(se):
    """Once tripped, kill switch blocks all new positions."""
    st = se.snapshot()
    st['policy']['kill_switch'] = True
    st['policy']['kill_switch_reason'] = 'test'
    se._write_state(st)
    gate = se.can_open_position(cash=100_000.0, realized=0.0)
    assert gate['allowed'] is False
    assert 'KILL SWITCH' in gate['reason']


def test_reset_kill_switch_human_only(se):
    st = se.snapshot()
    st['policy']['kill_switch'] = True
    se._write_state(st)
    se.reset_kill_switch(reason='operator')
    st2 = se.snapshot()
    assert st2['policy']['kill_switch'] is False
    assert st2['last_reset']['by'] == 'operator'


def test_peak_equity_tracks(se):
    se.update(realized_pnl=10_000.0, cash=110_000.0)
    se.update(realized_pnl=5_000.0, cash=105_000.0)
    st = se.snapshot()
    assert st['peak_equity'] == pytest.approx(120_000.0)


def test_state_persists_across_calls(se):
    se.update(realized_pnl=8_000.0, cash=108_000.0)
    # New "process" reads the same file.
    st = se.snapshot()
    assert st['realized_total'] == pytest.approx(8_000.0)
    assert st['banked'] == pytest.approx(4_800.0)
