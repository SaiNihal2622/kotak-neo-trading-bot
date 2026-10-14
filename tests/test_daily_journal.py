"""Tests for the daily P&L + fills journal (2026-10-13)."""

import sys
from pathlib import Path

import pytest

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
sys.path.insert(0, str(ROOT / 'scripts'))
import daily_journal as dj


def test_helpers_present():
    assert hasattr(dj, 'build')
    assert hasattr(dj, '_today_infos')
    assert hasattr(dj, '_realized_pnl')


def test_filename_escape():
    assert dj._filename_escape('2026-10-13') == '20261013'


def test_realized_pnl_returns_float(monkeypatch):
    monkeypatch.setattr(dj, '_read_json', lambda p, default=None: {'realized_total': 0} if 'survival' in str(p) else {'realized_pnl': 0})
    v = dj._realized_pnl()
    assert isinstance(v, float)


def test_build_writes_file(monkeypatch, tmp_path):
    """build() must produce a markdown file and machine-readable json."""
    monkeypatch.setattr(dj, 'VAULT', tmp_path)
    monkeypatch.setattr(dj, 'DAILY_DIR', tmp_path)
    monkeypatch.setattr(dj, 'DATA', tmp_path)
    # minimal state files
    (tmp_path / 'paper_state.json').write_text(
        '{"cash": 100000, "realized_pnl": 0, "orders": {}, "positions": {}}',
        encoding='utf-8')
    (tmp_path / 'survival_state.json').write_text(
        '{"realized_total": 0, "policy": {}}', encoding='utf-8')
    # decisions jsonl with a HOLD today
    (tmp_path / 'quant_service_decisions.jsonl').write_text(
        '{"ts": "2026-10-13T10:00:00+05:30", "decision": {"type": "HOLD", "strategy": "x"}}\n',
        encoding='utf-8')
    # empty log files
    (tmp_path / 'quant_service.log').write_text('', encoding='utf-8')
    (tmp_path / 'order_rejections.jsonl').write_text('', encoding='utf-8')

    p = dj.build()
    assert p.exists()
    text = p.read_text(encoding='utf-8')
    assert 'Trading Day' in text
    assert 'Realized P&L' in text


def test_build_captures_blocked_signal(monkeypatch, tmp_path):
    """A suppressed OPEN must appear under 'Signals attempted but blocked'."""
    monkeypatch.setattr(dj, 'VAULT', tmp_path)
    monkeypatch.setattr(dj, 'DAILY_DIR', tmp_path)
    monkeypatch.setattr(dj, 'DATA', tmp_path)
    # isolate the module constants so the test reads tmp files, not the real log
    monkeypatch.setattr(dj, 'QUANT_LOG', tmp_path / 'quant_service.log')
    monkeypatch.setattr(dj, 'DECISIONS', tmp_path / 'quant_service_decisions.jsonl')
    monkeypatch.setattr(dj, 'REJECTIONS', tmp_path / 'order_rejections.jsonl')
    import datetime
    today = datetime.date.today().isoformat()
    (tmp_path / 'paper_state.json').write_text(
        '{"cash": 100000, "realized_pnl": 0, "orders": {}, "positions": {}}', encoding='utf-8')
    (tmp_path / 'survival_state.json').write_text('{"realized_total": 0}', encoding='utf-8')
    (tmp_path / 'quant_service_decisions.jsonl').write_text('', encoding='utf-8')
    (tmp_path / 'order_rejections.jsonl').write_text('', encoding='utf-8')
    (tmp_path / 'quant_service.log').write_text(
        f'[{today}T14:57:16+05:30] ACTION-SUPPRESSED: OPEN after 14:30 IST (intraday no_new_trades_after); dropping to log only.\n',
        encoding='utf-8')
    p = dj.build()
    text = p.read_text(encoding='utf-8')
    assert 'Signals attempted but blocked' in text
    assert '14:57' in text
