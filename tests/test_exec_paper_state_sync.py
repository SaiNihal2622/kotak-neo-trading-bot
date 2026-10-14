"""Tests for the exec-gateway -> paper_state.json sync fix (2026-10-14).

Root cause: the exec gateway filled orders into the core's SQLite event store
(/api/order_fill) but NEVER wrote data_cache/paper_state.json, which is the
store the dashboard, daily journal, survival engine and bot all read. So
every real fill was stranded in an orphan store and the system LOOKED like
it never traded (positions stayed 0, realized 0, journal empty). The fix
writes each fill back into paper_state.json.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
sys.path.insert(0, str(ROOT))
from system.exec.exec_gateway import ExecGateway


@pytest.fixture()
def gw(tmp_path, monkeypatch):
    g = ExecGateway(core_url='http://127.0.0.1:8510')
    monkeypatch.setattr('system.exec.exec_gateway._now_iso_ist',
                        lambda: '2026-10-14T12:00:00+05:30')
    _ps = tmp_path / 'paper_state.json'
    _ps.write_text('{"cash": 100000, "realized_pnl": 0, "orders": {}, "positions": {}}',
                   encoding='utf-8')
    g.paper_state_path = str(_ps)  # redirect sync to the tmp file
    return g, _ps


def test_sync_writes_position(gw):
    g, ps_path = gw
    g._sync_paper_state({
        'symbol': 'NIFTY22OCT2622050CE', 'side': 'BUY',
        'client_order_id': 'ord-1', 'underlying': 'NIFTY',
        'strike': 22050, 'option_type': 'CE', 'expiry': '2026-10-22',
    }, 67.0, 150)
    ps = json.loads(ps_path.read_text(encoding='utf-8'))
    assert ps['positions']['NIFTY22OCT2622050CE']['qty'] == 150
    assert ps['positions']['NIFTY22OCT2622050CE']['avg_price'] == 67.0
    assert ps['orders']['ord-1']['status'] == 'complete'


def test_sync_sell_reduces_position(gw):
    g, ps_path = gw
    # open 150 then sell 150 -> position closes
    g._sync_paper_state({'symbol': 'NIFTY22500PE', 'side': 'BUY', 'client_order_id': 'o1',
                         'underlying': 'NIFTY'}, 64.8, 150)
    g._sync_paper_state({'symbol': 'NIFTY22500PE', 'side': 'SELL', 'client_order_id': 'o2',
                         'underlying': 'NIFTY'}, 60.0, 150)
    ps = json.loads(ps_path.read_text(encoding='utf-8'))
    assert 'NIFTY22500PE' not in ps['positions']  # net-zero -> removed


def test_sync_weighted_avg_price(gw):
    g, ps_path = gw
    g._sync_paper_state({'symbol': 'NIFTY22900CE', 'side': 'BUY', 'client_order_id': 'a',
                         'underlying': 'NIFTY'}, 60.0, 150)
    g._sync_paper_state({'symbol': 'NIFTY22900CE', 'side': 'BUY', 'client_order_id': 'b',
                         'underlying': 'NIFTY'}, 70.0, 150)
    ps = json.loads(ps_path.read_text(encoding='utf-8'))
    assert ps['positions']['NIFTY22900CE']['qty'] == 300
    assert ps['positions']['NIFTY22900CE']['avg_price'] == 65.0


def test_sync_handles_missing_file(gw):
    g, _ps = gw
    _ps.unlink(missing_ok=True)
    g._sync_paper_state({'symbol': 'NIFTY', 'side': 'BUY', 'client_order_id': 'x',
                         'underlying': 'NIFTY'}, 22375.0, 75)
    # no exception raised is the pass
