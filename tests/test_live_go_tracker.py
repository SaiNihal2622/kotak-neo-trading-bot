"""FIX 2026-09-17: tests for the live-go policy tracker.

Validates:
- Policy file load + default creation
- Consecutive green day counting (with streak reset on any losing day)
- Cumulative return computation from by_day
- All three conditions evaluated correctly (AND of streak + return + gates)
- Status JSON written to data_cache/live_go_status.json
- Override via live_go_policy.json takes effect
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def test_consecutive_green_days_streak():
    """FIX 2026-09-17: streak counts trailing green days and resets on red."""
    from scripts.live_go_tracker import _consecutive_green_days
    # Layout: RED on Sep 12, GREEN on Sep 13-16
    daily_pnl = {
        "2026-09-10": 100,
        "2026-09-11": 200,
        "2026-09-12": -50,  # RED
        "2026-09-13": 300,
        "2026-09-14": 400,
        "2026-09-15": 500,
        "2026-09-16": 600,
    }
    streak, last_day = _consecutive_green_days(daily_pnl)
    # Last 4 days (13, 14, 15, 16) are all green → streak = 4
    assert streak == 4
    assert last_day == "2026-09-16"


def test_consecutive_green_days_zero_when_last_is_red():
    from scripts.live_go_tracker import _consecutive_green_days
    daily_pnl = {
        "2026-09-15": 100,
        "2026-09-16": -50,  # RED breaks streak
    }
    streak, last_day = _consecutive_green_days(daily_pnl)
    assert streak == 0


def test_consecutive_green_days_empty_input():
    from scripts.live_go_tracker import _consecutive_green_days
    streak, last_day = _consecutive_green_days({})
    assert streak == 0


def test_cumulative_return_pct():
    from scripts.live_go_tracker import _cumulative_return_pct
    daily_pnl = {
        "2026-09-10": 1000,
        "2026-09-11": 2000,
        "2026-09-12": 500,
    }
    cum, pct = _cumulative_return_pct(daily_pnl, baseline=100000)
    assert cum == 3500
    assert abs(pct - 3.5) < 0.01


def test_cumulative_return_pct_zero_baseline_protected():
    from scripts.live_go_tracker import _cumulative_return_pct
    cum, pct = _cumulative_return_pct({"x": 100}, baseline=0)
    assert cum == 0
    assert pct == 0


def test_load_policy_creates_default_when_missing():
    """FIX 2026-09-17: live_go_tracker.py auto-creates the policy file
    on first run if missing. Without this, the bot would crash at 15:30
    IST on day 1 of operation.
    """
    with tempfile.TemporaryDirectory() as tmp:
        # Point the DCACHE module-level constant at our tmpdir
        import scripts.live_go_tracker as _lgt
        orig_dcache = _lgt.DCACHE
        try:
            _lgt.DCACHE = Path(tmp)
            policy = _lgt._load_policy()
            assert policy["min_consecutive_green_days"] == 10
            assert policy["min_cumulative_return_pct"] == 15.0
            assert policy["min_avg_daily_pnl_rs"] == 1000
            assert policy["min_total_trades"] == 30
            # File should have been written
            assert (Path(tmp) / "live_go_policy.json").exists()
        finally:
            _lgt.DCACHE = orig_dcache


def test_load_policy_respects_overrides():
    """FIX 2026-09-17: user can edit live_go_policy.json to override defaults."""
    with tempfile.TemporaryDirectory() as tmp:
        import scripts.live_go_tracker as _lgt
        orig_dcache = _lgt.DCACHE
        try:
            _lgt.DCACHE = Path(tmp)
            custom = {
                "_comment": "test override",
                "min_consecutive_green_days": 3,
                "min_cumulative_return_pct": 2.5,
                "starting_capital_baseline": 100000,
            }
            (Path(tmp) / "live_go_policy.json").write_text(json.dumps(custom), encoding="utf-8")
            policy = _lgt._load_policy()
            assert policy["min_consecutive_green_days"] == 3
            assert policy["min_cumulative_return_pct"] == 2.5
        finally:
            _lgt.DCACHE = orig_dcache


def test_main_writes_status_json():
    """FIX 2026-09-17: the tracker writes live_go_status.json with all
    computed fields. The dashboard reads this to show progress.
    """
    # Run the tracker against the real production data
    import subprocess
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "live_go_tracker.py")],
        capture_output=True, text=True, timeout=60,
    )
    # Should exit 0 (returns 0 from main)
    assert r.returncode == 0, f"tracker failed: {r.stderr}"
    # Status file should exist
    status_path = ROOT / "data_cache" / "live_go_status.json"
    assert status_path.exists()
    with open(status_path) as f:
        status = json.load(f)
    # Required fields present
    assert "ready_for_live" in status
    assert "conditions" in status
    assert "consecutive_green_days" in status["conditions"]
    assert "cumulative_return" in status["conditions"]
    assert "all_gates_passing" in status["conditions"]
    assert "missing_to_ready" in status
    assert "current" in status
    assert "policy" in status


def test_all_conditions_must_hold():
    """FIX 2026-09-17: ready_for_live is TRUE only if ALL conditions are
    met. If even one fails, the gate is NOT READY.
    """
    # Use a mock to control each condition individually
    with patch("scripts.live_go_tracker._consecutive_green_days", return_value=(10, "2026-09-16")), \
         patch("scripts.live_go_tracker._cumulative_return_pct", return_value=(15000.0, 15.0)), \
         patch("scripts.live_go_tracker._avg_daily_pnl_rs", return_value=1500.0), \
         patch("scripts.live_go_tracker._total_trades", return_value=35), \
         patch("scripts.live_go_tracker._all_gates_passing", return_value=(True, "100%")):
        import scripts.live_go_tracker as _lgt
        with tempfile.TemporaryDirectory() as tmp:
            orig_dcache = _lgt.DCACHE
            try:
                _lgt.DCACHE = Path(tmp)
                _lgt.main()
                status = json.loads((Path(tmp) / "live_go_status.json").read_text())
                assert status["ready_for_live"] is True
            finally:
                _lgt.DCACHE = orig_dcache
    # Now break one condition (streak too short)
    with patch("scripts.live_go_tracker._consecutive_green_days", return_value=(3, "2026-09-16")), \
         patch("scripts.live_go_tracker._cumulative_return_pct", return_value=(15000.0, 15.0)), \
         patch("scripts.live_go_tracker._avg_daily_pnl_rs", return_value=1500.0), \
         patch("scripts.live_go_tracker._total_trades", return_value=35), \
         patch("scripts.live_go_tracker._all_gates_passing", return_value=(True, "100%")):
        import scripts.live_go_tracker as _lgt
        with tempfile.TemporaryDirectory() as tmp:
            orig_dcache = _lgt.DCACHE
            try:
                _lgt.DCACHE = Path(tmp)
                _lgt.main()
                status = json.loads((Path(tmp) / "live_go_status.json").read_text())
                assert status["ready_for_live"] is False
                assert "consecutive_green_days" in status["missing_to_ready"]
            finally:
                _lgt.DCACHE = orig_dcache


def test_avg_daily_pnl_excludes_zero_days():
    """FIX 2026-09-18 19:35: avg daily P&L excludes zero-PnL days (no-trade
    days should not lower the average).
    """
    from scripts.live_go_tracker import _avg_daily_pnl_rs
    daily_pnl = {
        "2026-09-15": 2000.0,
        "2026-09-16": 0.0,    # zero (no trade)
        "2026-09-17": 3000.0,
        "2026-09-18": 0.0,    # zero (no trade)
    }
    avg = _avg_daily_pnl_rs(daily_pnl)
    # Active days: [2000, 3000] → avg = 2500 (NOT 1250, which would include zeros)
    assert avg == 2500.0


def test_avg_daily_pnl_handles_all_zero():
    """FIX 2026-09-18 19:35: when no active (non-zero) days, avg = 0."""
    from scripts.live_go_tracker import _avg_daily_pnl_rs
    assert _avg_daily_pnl_rs({}) == 0.0
    assert _avg_daily_pnl_rs({"2026-09-15": 0.0}) == 0.0


def test_industry_standard_defaults():
    """FIX 2026-09-18 19:35: default policy thresholds are industry-standard
    (10 days / 15% / Rs.1,000/day avg / 30 trades).
    """
    from scripts.live_go_tracker import _load_policy
    # Read the production policy file (which has been updated)
    prod_policy = ROOT / "data_cache" / "live_go_policy.json"
    if prod_policy.exists():
        policy = json.loads(prod_policy.read_text(encoding="utf-8"))
    else:
        policy = _load_policy()
    assert policy.get("min_consecutive_green_days") == 10
    assert policy.get("min_cumulative_return_pct") == 15.0
    assert policy.get("min_avg_daily_pnl_rs") == 1000
    assert policy.get("min_total_trades") == 30


def test_total_trades_reads_strategy_perf():
    """FIX 2026-09-18 19:35: total_trades helper reads n_trades from
    strategy_performance.json (the aggregator's authoritative count).
    """
    from scripts.live_go_tracker import _total_trades
    with tempfile.TemporaryDirectory() as tmp:
        import scripts.live_go_tracker as _lgt
        orig_dcache = _lgt.DCACHE
        try:
            _lgt.DCACHE = Path(tmp)
            perf_dir = Path(tmp) / "performance"
            perf_dir.mkdir(parents=True, exist_ok=True)
            (perf_dir / "strategy_performance.json").write_text(
                json.dumps({"n_trades": 42}), encoding="utf-8"
            )
            assert _total_trades() == 42
        finally:
            _lgt.DCACHE = orig_dcache