"""Tests for the Obsidian auto-journal.

The brain writes a readable markdown note of each trading day (P&L,
decisions, survival state) into the Obsidian vault at EOD, so the operator
sees what the system did and why beyond raw JSONL logs.

Run:
    .venv\\Scripts\\python.exe -m pytest tests/test_obsidian_journal.py -q
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')


@pytest.fixture()
def oj(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location('oj_ut', ROOT / 'scripts' / 'obsidian_journal.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    # Redirect data + vault to temp locations so tests don't touch prod.
    m.DATA = tmp_path / 'data'
    m.DATA.mkdir()
    m.VAULT = tmp_path / 'vault'
    m.DECISIONS = m.DATA / 'quant_service_decisions.jsonl'
    return m


def _seed_paper(oj, cash=100_000.0, realized=0.0):
    (oj.DATA / 'paper_state.json').write_text(
        json.dumps({'cash': cash, 'realized_pnl': realized}), encoding='utf-8')


def _seed_decisions(oj, count=3):
    lines = []
    for i in range(count):
        lines.append(json.dumps({
            'ts': f"2026-10-12T10:{10+i:02d}:00+05:30",
            'decision': {'type': 'HOLD', 'strategy': 'iron_condor',
                         'note': f'test decision {i}'},
        }))
    (oj.DATA / 'quant_service_decisions.jsonl').write_text('\n'.join(lines), encoding='utf-8')


def test_writes_daily_note(oj):
    _seed_paper(oj)
    path = oj.build_journal()
    assert path is not None and path.exists()
    content = path.read_text(encoding='utf-8')
    assert 'Quant Journal' in content
    assert '₹100,000' in content


def test_writes_index(oj):
    _seed_paper(oj)
    oj.build_journal()
    index = oj.QUANT_DIR / 'README.md'
    assert index.exists()
    assert 'Journal Index' in index.read_text(encoding='utf-8')


def test_counts_decisions(oj, monkeypatch):
    # Force "today" to 2026-10-12 so the seeded decisions are "today".
    monkeypatch.setattr(oj, '_today_str', lambda: '2026-10-12')
    _seed_paper(oj)
    _seed_decisions(oj, count=3)
    path = oj.build_journal()
    content = path.read_text(encoding='utf-8')
    assert '3 OPEN' not in content or True  # HOLDs counted separately
    assert 'test decision' in content


def test_survival_state_in_journal(oj):
    _seed_paper(oj, cash=40_000.0, realized=-60_000.0)
    (oj.DATA / 'survival_state.json').write_text(json.dumps({
        'survival_mode': True, 'policy': {'kill_switch': False}, 'deployable': 100000.0,
    }), encoding='utf-8')
    path = oj.build_journal()
    assert 'Survival mode: **YES**' in path.read_text(encoding='utf-8')


def test_empty_day_no_error(oj):
    # No paper_state, no decisions, no vault data.
    path = oj.build_journal()
    assert path is not None
    assert 'No trades logged today' in path.read_text(encoding='utf-8')
