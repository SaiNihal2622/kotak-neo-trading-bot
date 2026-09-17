"""Tests for dashboard/real_provider.py — the live-data wiring for Streamlit.

Verifies that RealDataProvider reads paper_state, strategy_performance, and
other data_cache/*.json files correctly and exposes them as the abstract
DataProvider interface (AccountSnapshot, Position, PnLHistory, RiskState,
BotConfig). Uses a temp dir for the data_cache so the production state is
untouched.
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def _make_data_cache(tmp_path: Path, **overrides) -> Path:
    """Create a minimal data_cache layout under tmp_path."""
    dc = tmp_path / "data_cache"
    dc.mkdir(parents=True, exist_ok=True)
    perf = dc / "performance"
    perf.mkdir(exist_ok=True)
    # Minimal paper_state
    paper_state = {
        "cash": overrides.get("cash", 109994.50),
        "realized_pnl": overrides.get("realized_pnl", 9994.50),
        "positions": overrides.get("positions", {}),
        "orders": overrides.get("orders", {"O1": {"symbol": "NIFTY17SEP2623200CE", "side": "BUY", "qty": 75}}),
    }
    (dc / "paper_state.json").write_text(json.dumps(paper_state), encoding="utf-8")
    # Minimal strategy_performance
    today = datetime.now().strftime("%Y-%m-%d")
    by_day = overrides.get("by_day", {
        today: {"trades": 7, "pnl": 15006.75},
    })
    sp = {
        "ts": datetime.now().isoformat(),
        "n_trades": 7,
        "total_pnl": 15006.75,
        "sharpe_30d": 3.41,
        "by_strategy": {},
        "by_underlying": {},
        "by_day": by_day,
    }
    perf.joinpath("strategy_performance.json").write_text(json.dumps(sp), encoding="utf-8")
    return dc


def test_real_provider_imports(monkeypatch):
    """RealDataProvider can be imported without errors."""
    from dashboard.real_provider import RealDataProvider
    assert RealDataProvider is not None


def test_real_provider_reads_paper_state(monkeypatch, tmp_path):
    """AccountSnapshot.equity matches paper_state.cash."""
    dc = _make_data_cache(tmp_path, cash=123456.78, realized_pnl=20000.0)
    monkeypatch.setattr("dashboard.real_provider.DCACHE", dc)
    from dashboard.real_provider import RealDataProvider
    p = RealDataProvider()
    acc = p.get_account()
    assert acc.equity == 123456.78
    assert acc.open_positions == 0


def test_real_provider_day_pnl_from_by_day(monkeypatch, tmp_path):
    """Day P&L comes from by_day[today], not journal scan."""
    today = datetime.now().strftime("%Y-%m-%d")
    dc = _make_data_cache(tmp_path, by_day={today: {"trades": 5, "pnl": 7777.77}})
    monkeypatch.setattr("dashboard.real_provider.DCACHE", dc)
    from dashboard.real_provider import RealDataProvider
    p = RealDataProvider()
    acc = p.get_account()
    assert acc.day_pnl == 7777.77


def test_real_provider_positions_empty(monkeypatch, tmp_path):
    """Empty positions → empty list, open_positions=0."""
    dc = _make_data_cache(tmp_path, positions={})
    monkeypatch.setattr("dashboard.real_provider.DCACHE", dc)
    from dashboard.real_provider import RealDataProvider
    p = RealDataProvider()
    assert p.get_positions() == []


def test_real_provider_positions_with_open(monkeypatch, tmp_path):
    """Open position with qty>0 → LONG, qty<0 → SHORT."""
    today = datetime.now().strftime("%Y-%m-%d")
    expiry = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
    positions = {
        "NIFTY17SEP2623500CE": {
            "qty": 75,
            "avg_price": 100.0,
            "ltp": 110.0,
            "underlying": "NIFTY",
            "strike": 23500,
            "option_type": "CE",
            "expiry": expiry,
        },
        "BANKNIFTY17SEP2656800PE": {
            "qty": -30,
            "avg_price": 500.0,
            "ltp": 480.0,
            "underlying": "BANKNIFTY",
            "strike": 56800,
            "option_type": "PE",
            "expiry": expiry,
        },
    }
    dc = _make_data_cache(tmp_path, positions=positions)
    monkeypatch.setattr("dashboard.real_provider.DCACHE", dc)
    from dashboard.real_provider import RealDataProvider
    p = RealDataProvider()
    pos_list = p.get_positions()
    assert len(pos_list) == 2
    long_p = next(x for x in pos_list if x.side == "LONG")
    short_p = next(x for x in pos_list if x.side == "SHORT")
    assert long_p.symbol == "NIFTY17SEP2623500CE"
    assert long_p.qty == 75
    assert long_p.entry == 100.0
    assert long_p.current == 110.0
    assert long_p.pnl == 750.0  # (110 - 100) * 75
    assert long_p.pnl_pct == pytest.approx(10.0, abs=0.01)
    assert short_p.symbol == "BANKNIFTY17SEP2656800PE"
    assert short_p.qty == 30
    assert short_p.pnl == 600.0  # (-480 - (-500)) * abs(-30)


def test_real_provider_pnl_history(monkeypatch, tmp_path):
    """get_pnl_history returns sorted dates + equity curve starting at baseline."""
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    by_day = {
        yesterday: {"pnl": 5000.0, "trades": 3},
        today: {"pnl": 3000.0, "trades": 2},
    }
    dc = _make_data_cache(tmp_path, by_day=by_day)
    monkeypatch.setattr("dashboard.real_provider.DCACHE", dc)
    from dashboard.real_provider import RealDataProvider
    p = RealDataProvider()
    hist = p.get_pnl_history()
    assert len(hist.dates) == 2
    assert hist.dates[0] < hist.dates[1]  # sorted ascending
    # Baseline = 100000, +5000 then +3000 = 108000
    assert hist.equity[-1] == 108000.0


def test_real_provider_risk_state(monkeypatch, tmp_path):
    """RiskState.daily_loss_used is 0 when no negative days."""
    dc = _make_data_cache(tmp_path)
    monkeypatch.setattr("dashboard.real_provider.DCACHE", dc)
    from dashboard.real_provider import RealDataProvider
    p = RealDataProvider()
    risk = p.get_risk_state()
    assert risk.daily_loss_used >= 0
    assert risk.daily_loss_limit > 0  # default from settings
    assert risk.kill_switch is False


def test_real_provider_kill_switch_on_audit_error(monkeypatch, tmp_path):
    """kill_switch=True when any audit subsystem is in error state."""
    dc = _make_data_cache(tmp_path)
    audit = {
        "subsystems": {
            "chain_health": {"status": "ok"},
            "fake_subsys": {"status": "error", "details": "broken"},
        }
    }
    (dc / "system_audit.json").write_text(json.dumps(audit), encoding="utf-8")
    monkeypatch.setattr("dashboard.real_provider.DCACHE", dc)
    from dashboard.real_provider import RealDataProvider
    p = RealDataProvider()
    risk = p.get_risk_state()
    assert risk.kill_switch is True


def test_real_provider_get_config_includes_live_go(monkeypatch, tmp_path):
    """BotConfig.data['live_go_progress'] populated from live_go_status.json."""
    dc = _make_data_cache(tmp_path)
    lgs = {
        "current": {"consecutive_green_days": 3, "cumulative_return_pct": 87.71},
        "ready_for_live": False,
        "missing_to_ready": ["consecutive_green_days"],
    }
    (dc / "live_go_status.json").write_text(json.dumps(lgs), encoding="utf-8")
    monkeypatch.setattr("dashboard.real_provider.DCACHE", dc)
    from dashboard.real_provider import RealDataProvider
    p = RealDataProvider()
    cfg = p.get_config().data
    lgs_block = cfg.get("live_go_progress") or {}
    assert lgs_block.get("streak") == 3
    assert lgs_block.get("return_pct") == 87.71
    assert lgs_block.get("ready") is False
    assert "consecutive_green_days" in (lgs_block.get("missing") or [])


def test_real_provider_update_config_returns_false(monkeypatch, tmp_path):
    """update_config is read-only (returns False)."""
    dc = _make_data_cache(tmp_path)
    monkeypatch.setattr("dashboard.real_provider.DCACHE", dc)
    from dashboard.real_provider import RealDataProvider
    p = RealDataProvider()
    assert p.update_config("some_key", "value") is False


def test_real_provider_handles_missing_files(monkeypatch, tmp_path):
    """No data_cache → RealDataProvider returns safe defaults, doesn't crash."""
    dc = tmp_path / "empty_cache"
    dc.mkdir()
    monkeypatch.setattr("dashboard.real_provider.DCACHE", dc)
    from dashboard.real_provider import RealDataProvider
    p = RealDataProvider()
    acc = p.get_account()
    assert acc.equity == 0.0
    assert acc.open_positions == 0
    assert p.get_positions() == []
    # Should not raise on news/signals/risk either
    p.get_news()
    p.get_signals()
    p.get_risk_state()
