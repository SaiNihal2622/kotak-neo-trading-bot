"""Tests for the UNLEASHED mode (no caps) and the max-drawdown safety net.

FIX 2026-09-09 00:56: user said "no caps, I want to see profits". The LLM
brain is now the SOLE risk manager. The 10-lot hard cap is GONE.
The VIX skip, opening buffer, macro blackout are GONE. The only
remaining hard limit is the 50% max-drawdown auto-pause (catastrophic
blow-up protection, not a strategy cap).
"""
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


# ---------- settings.yaml unleashed values ----------

def test_settings_no_vix_skip():
    """VIX skip threshold should be effectively disabled (>= 100)."""
    cfg = (ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    # skip_above should be high (was 22.0, now >= 100)
    m = re.search(r"skip_above:\s*([\d.]+)", cfg)
    assert m, "skip_above not found in settings.yaml"
    val = float(m.group(1))
    assert val >= 100.0, f"VIX skip_above should be >= 100 (UNLEASHED), got {val}"


def test_settings_no_opening_buffer():
    """avoid_first_5_min_after_open should be false in UNLEASHED mode."""
    cfg = (ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    # Find the line and check that it's false
    m = re.search(r"avoid_first_5_min_after_open:\s*(\w+)", cfg)
    assert m, "avoid_first_5_min_after_open not found"
    val = m.group(1).lower()
    assert val == "false", f"avoid_first_5_min_after_open should be false in UNLEASHED, got {val}"


def test_settings_no_event_blackout():
    """event_blackout_min_before/after should be 0 in UNLEASHED mode."""
    cfg = (ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    # Should be 0
    m_before = re.search(r"event_blackout_min_before:\s*(\d+)", cfg)
    m_after = re.search(r"event_blackout_min_after:\s*(\d+)", cfg)
    assert m_before, "event_blackout_min_before not found"
    assert m_after, "event_blackout_min_after not found"
    assert int(m_before.group(1)) == 0, f"event_blackout_min_before should be 0, got {m_before.group(1)}"
    assert int(m_after.group(1)) == 0, f"event_blackout_min_after should be 0, got {m_after.group(1)}"


def test_settings_position_cap_high():
    """position_cap should be >= 50 in UNLEASHED mode (was 2)."""
    cfg = (ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    m = re.search(r"position_cap:\s*(\d+)", cfg)
    assert m, "position_cap not found"
    val = int(m.group(1))
    assert val >= 50, f"position_cap should be >= 50 (UNLEASHED), got {val}"


def test_settings_max_lots_50():
    """max_lots should be >= 50 in UNLEASHED mode (was 3)."""
    cfg = (ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    m = re.search(r"max_lots:\s*(\d+)", cfg)
    assert m, "max_lots not found"
    val = int(m.group(1))
    assert val >= 50, f"max_lots should be >= 50 (UNLEASHED), got {val}"


def test_settings_max_drawdown_50pct():
    """The catastrophic drawdown safety net should be 50% (only remaining hard cap)."""
    cfg = (ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    m = re.search(r"max_drawdown_pct:\s*([\d.]+)", cfg)
    assert m, "max_drawdown_pct not found"
    val = float(m.group(1))
    assert val == 50.0, f"max_drawdown_pct should be 50.0, got {val}"
    # auto_pause should be true
    m2 = re.search(r"auto_pause_on_max_drawdown:\s*(\w+)", cfg)
    assert m2, "auto_pause_on_max_drawdown not found"
    assert m2.group(1).lower() == "true", f"auto_pause should be true, got {m2.group(1)}"


def test_settings_per_trade_loss_pct_100():
    """per-trade loss % should be 100 (effectively unlimited) in UNLEASHED mode."""
    cfg = (ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    # The base preset should have max_loss_per_trade_pct = 100.0
    m = re.search(r"max_loss_per_trade_pct:\s*([\d.]+)", cfg)
    assert m, "max_loss_per_trade_pct not found"
    val = float(m.group(1))
    assert val >= 99.0, f"per-trade loss % should be >= 99 (UNLEASHED), got {val}"


# ---------- brain unleashed: no 10-lot cap ----------

def test_brain_no_10_lot_cap_in_normalize():
    """_normalize_decision should not cap qty at 10 anymore."""
    from scripts import quant_service
    d = {
        "type": "OPEN",
        "underlying": "NIFTY",
        "conviction": 100,
        "legs": [{"side": "BUY", "qty": 50, "strike": 24000, "opt_type": "PE"}],
    }
    out = quant_service._normalize_decision(d)
    # qty should be preserved (no 10-lot cap), but min 1
    assert out["legs"][0]["qty"] == 50, (
        f"UNLEASHED: qty=50 should be preserved (no 10-lot cap), got {out['legs'][0]['qty']}"
    )


def test_brain_no_10_lot_cap_in_write_decision():
    """write_decision with conviction=100 and qty=50 should keep qty=50 (no cap)."""
    from scripts import quant_service
    from datetime import datetime, timezone, timedelta
    ist = timezone(timedelta(hours=5, minutes=30))
    fake_now = datetime(2026, 9, 9, 10, 0, 0, tzinfo=ist)
    class FakeDatetime:
        @classmethod
        def now(cls, tz=None):
            return fake_now if tz is None else fake_now.astimezone(tz)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        actions_path = Path(tmp) / "quant_actions.json"
        decisions_path = Path(tmp) / "decisions.jsonl"
        original_actions = quant_service.ACTIONS
        original_decisions = quant_service.DECISIONS
        original_datetime = quant_service.datetime
        quant_service.ACTIONS = actions_path
        quant_service.DECISIONS = str(decisions_path)
        quant_service.datetime = FakeDatetime
        quant_service.log = lambda x: None
        try:
            decision = {
                "type": "OPEN",
                "underlying": "NIFTY",
                "strategy": "x",
                "conviction": 100,
                "legs": [{"side": "BUY", "qty": 50, "strike": 24000, "opt_type": "PE"}],
                "rationale": "test",
            }
            quant_service.write_decision(decision)
            ad = json.loads(actions_path.read_text(encoding="utf-8"))
            assert ad["actions"][0]["legs"][0]["qty"] == 50, (
                f"UNLEASHED: qty=50 should be preserved, got {ad['actions'][0]['legs'][0]['qty']}"
            )
        finally:
            quant_service.ACTIONS = original_actions
            quant_service.DECISIONS = original_decisions
            quant_service.datetime = original_datetime


def test_brain_min_1_lot_still_enforced():
    """Min 1 lot still enforced (qty=0 doesn't make sense)."""
    from scripts import quant_service
    from datetime import datetime, timezone, timedelta
    ist = timezone(timedelta(hours=5, minutes=30))
    fake_now = datetime(2026, 9, 9, 10, 0, 0, tzinfo=ist)
    class FakeDatetime:
        @classmethod
        def now(cls, tz=None):
            return fake_now if tz is None else fake_now.astimezone(tz)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        actions_path = Path(tmp) / "quant_actions.json"
        decisions_path = Path(tmp) / "decisions.jsonl"
        original_actions = quant_service.ACTIONS
        original_decisions = quant_service.DECISIONS
        original_datetime = quant_service.datetime
        quant_service.ACTIONS = actions_path
        quant_service.DECISIONS = str(decisions_path)
        quant_service.datetime = FakeDatetime
        quant_service.log = lambda x: None
        try:
            # conviction=0 + qty=0 → min 1
            decision = {
                "type": "OPEN",
                "underlying": "NIFTY",
                "strategy": "x",
                "conviction": 0,
                "legs": [{"side": "BUY", "qty": 0, "strike": 24000, "opt_type": "PE"}],
                "rationale": "test",
            }
            quant_service.write_decision(decision)
            ad = json.loads(actions_path.read_text(encoding="utf-8"))
            assert ad["actions"][0]["legs"][0]["qty"] == 1, (
                f"min 1 lot must still be enforced, got {ad['actions'][0]['legs'][0]['qty']}"
            )
        finally:
            quant_service.ACTIONS = original_actions
            quant_service.DECISIONS = original_decisions
            quant_service.datetime = original_datetime


# ---------- max-drawdown safety net in bot ----------

def test_bot_has_max_drawdown_safety_net():
    """The bot's main loop must check for max-drawdown auto-pause."""
    from pathlib import Path
    main_py = (ROOT / "kotak_bot" / "__main__.py").read_text(encoding="utf-8")
    assert "MAX-DRAWDOWN" in main_py, (
        "bot's main loop must check for MAX-DRAWDOWN auto-pause"
    )
    assert "AUTO-PAUSED" in main_py or "auto-paused" in main_py, (
        "bot's main loop must log/alert when auto-paused"
    )


def test_settings_has_drawdown_config():
    """settings.yaml must have max_drawdown_pct and auto_pause_on_max_drawdown."""
    cfg = (ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    assert "max_drawdown_pct" in cfg
    assert "auto_pause_on_max_drawdown" in cfg
