"""Tests for intraday mode + VIX-aware risk logic."""
import sys
from pathlib import Path
from datetime import datetime, time, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from kotak_bot.utils.clock import (
    IST, set_intraday, get_intraday, is_past_no_new_trades_time,
    is_past_force_square_off_time, is_in_opening_buffer, is_allow_overnight,
    vix_position_size_multiplier, vix_should_skip,
)


def test_intraday_defaults():
    """Default settings block all overnight positions."""
    set_intraday({})  # reset
    cfg = get_intraday()
    assert cfg["allow_overnight"] is False
    assert cfg["no_new_trades_after"] == time(13, 30)
    assert cfg["force_square_off_time"] == time(14, 30)
    print("  defaults: allow_overnight=False, no_new_trades_after=13:30, force_square_off=14:30")


def test_no_new_trades_after():
    set_intraday({"no_new_trades_after": "13:30"})
    # 13:29 — should NOT block
    now = datetime(2026, 8, 13, 13, 29, tzinfo=IST)
    assert is_past_no_new_trades_time(now) is False
    # 13:30 — should block (>=)
    now = datetime(2026, 8, 13, 13, 30, tzinfo=IST)
    assert is_past_no_new_trades_time(now) is True
    # 14:00 — should block
    now = datetime(2026, 8, 13, 14, 0, tzinfo=IST)
    assert is_past_no_new_trades_time(now) is True
    print("  no_new_trades_after: 13:29 pass, 13:30 block, 14:00 block")


def test_force_square_off_time():
    set_intraday({"force_square_off_time": "14:30"})
    # 14:29 — should NOT force
    now = datetime(2026, 8, 13, 14, 29, tzinfo=IST)
    assert is_past_force_square_off_time(now) is False
    # 14:30 — should force
    now = datetime(2026, 8, 13, 14, 30, tzinfo=IST)
    assert is_past_force_square_off_time(now) is True
    print("  force_square_off: 14:29 pass, 14:30 force")


def test_opening_buffer():
    set_intraday({"avoid_first_5_min_after_open": True})
    # 9:14 — pre-open, not in buffer
    now = datetime(2026, 8, 13, 9, 14, tzinfo=IST)
    assert is_in_opening_buffer(now) is False
    # 9:20 — opening, in buffer
    now = datetime(2026, 8, 13, 9, 20, tzinfo=IST)
    assert is_in_opening_buffer(now) is True
    # 9:30 — opening_end, NOT in buffer
    now = datetime(2026, 8, 13, 9, 30, tzinfo=IST)
    assert is_in_opening_buffer(now) is False
    print("  opening_buffer: 9:14 pass, 9:20 block, 9:30 pass")


def test_vix_position_size():
    # VIX <= 15 → 1.0x
    assert vix_position_size_multiplier(10.0) == 1.0
    assert vix_position_size_multiplier(15.0) == 1.0
    # VIX 15-18 → 0.75x
    assert vix_position_size_multiplier(16.0) == 0.75
    assert vix_position_size_multiplier(18.0) == 0.75
    # VIX 18-22 → 0.5x
    assert vix_position_size_multiplier(19.0) == 0.5
    assert vix_position_size_multiplier(22.0) == 0.5
    # VIX > 22 → 0.0x
    assert vix_position_size_multiplier(22.5) == 0.0
    assert vix_position_size_multiplier(40.0) == 0.0
    print("  vix_size: 10=1.0, 15=1.0, 16=0.75, 18=0.75, 19=0.5, 22=0.5, 22.5=0.0, 40=0.0")


def test_vix_should_skip():
    assert vix_should_skip(15.0, max_vix=22.0) is False
    assert vix_should_skip(22.0, max_vix=22.0) is False
    assert vix_should_skip(22.5, max_vix=22.0) is True
    assert vix_should_skip(50.0, max_vix=22.0) is True
    # custom threshold
    assert vix_should_skip(18.0, max_vix=15.0) is True
    assert vix_should_skip(14.0, max_vix=15.0) is False
    print("  vix_skip: 22.0=pass, 22.5=skip, custom 18>15=skip")


def test_allow_overnight_flag():
    set_intraday({"allow_overnight": True})
    assert is_allow_overnight() is True
    set_intraday({"allow_overnight": False})
    assert is_allow_overnight() is False
    print("  allow_overnight: True/False toggle works")


def test_set_intraday_invalid_input():
    """Bad inputs should keep defaults, not crash."""
    set_intraday({"no_new_trades_after": "not-a-time"})
    cfg = get_intraday()
    assert cfg["no_new_trades_after"] == time(13, 30)  # default preserved
    print("  invalid input: kept default 13:30, no crash")


if __name__ == "__main__":
    print("test_intraday_defaults"); test_intraday_defaults()
    print("test_no_new_trades_after"); test_no_new_trades_after()
    print("test_force_square_off_time"); test_force_square_off_time()
    print("test_opening_buffer"); test_opening_buffer()
    print("test_vix_position_size"); test_vix_position_size()
    print("test_vix_should_skip"); test_vix_should_skip()
    print("test_allow_overnight_flag"); test_allow_overnight_flag()
    print("test_set_intraday_invalid_input"); test_set_intraday_invalid_input()
    print("ALL PASS")
