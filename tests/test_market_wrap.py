"""Tests for the market wrap / pre-market readiness reporter.

Writes weekly P&L summary + Monday readiness checklist into the Obsidian
vault, all credential-free (reads the system's own state files).

Run:
    .venv\\Scripts\\python.exe -m pytest tests/test_market_wrap.py -q
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')


@pytest.fixture()
def mw(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location('mw_ut', ROOT / 'scripts' / 'market_wrap.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.DATA = tmp_path / 'data'
    m.DATA.mkdir()
    m.VAULT = tmp_path / 'vault'
    m.DECISIONS = m.DATA / 'quant_service_decisions.jsonl'
    # Stub service state so tests don't shell out to sc.exe.
    monkeypatch.setattr(m, '_service_state', lambda svc: 'RUNNING')
    return m


def _seed_decisions(mw, count=3):
    lines = [json.dumps({'ts': f"2026-10-08T10:0{i}:00+05:30", 'decision': {
        'type': 'CLOSE', 'strategy': 'iron_condor', 'rationale': f'trade {i}'}})
        for i in range(count)]
    lines.append(json.dumps({'ts': "2026-10-09T11:00:00+05:30", 'decision': {'type': 'HOLD'}}))
    (mw.DATA / 'quant_service_decisions.jsonl').write_text('\n'.join(lines), encoding='utf-8')


def test_build_weekly_writes_file(mw):
    (mw.DATA / 'survival_state.json').write_text(json.dumps({
        'realized_total': 1200.0, 'banked': 720.0, 'survival_mode': False}),
        encoding='utf-8')
    _seed_decisions(mw)
    path = mw.build_weekly()
    content = path.read_text(encoding='utf-8')
    assert 'Weekly Market Wrap' in content
    assert '₹1,200.00' in content
    assert 'iron_condor' in content


def test_build_weekly_no_trades(mw):
    path = mw.build_weekly()
    assert 'No trades this week' in path.read_text(encoding='utf-8')


def test_build_premarket_readiness(mw):
    (mw.DATA / 'quant_service_state.json').write_text(json.dumps({
        'llm_health': {'open': False}}), encoding='utf-8')
    path = mw.build_premarket_readiness()
    content = path.read_text(encoding='utf-8')
    assert 'READY' in content
    assert 'KotakBotPaper' in content
    assert 'LLM circuit: healthy' in content
