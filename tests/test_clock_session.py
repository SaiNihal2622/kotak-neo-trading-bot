"""Tests for market session / clock helpers — especially the pre_open exclusion.

Bug context: `is_market_open()` historically returned True during the NSE
pre_open window (9:00-9:15 IST), letting the bot place MARKET orders at
09:00:32 IST on 2026-08-24. Those paper fills happened at pre-open indicative
prices, not the real 9:15 auction opens. Production bug.

Fix: `is_market_open()` now returns False during pre_open. New `is_pre_open()`
helper is exposed for callers that explicitly want to know.
"""
from __future__ import annotations

import sys
from datetime import datetime, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kotak_bot.utils.clock import (
    is_market_open, is_pre_open, market_session, now_ist, set_market_hours,
)


def _at(h: int, m: int) -> datetime:
    """Build a datetime at h:m today, IST-naive for clock helpers."""
    return datetime(2026, 8, 24, h, m, 0)


def test_pre_open_excluded_from_market_open():
    """At 09:00 (pre_open), is_market_open must be False."""
    now = _at(9, 0)
    assert market_session(now) == "pre_open"
    assert is_pre_open(now) is True
    assert is_market_open(now) is False, \
        "pre_open must NOT count as market_open (was the 2026-08-24 bug)"
    print("  PASS: 09:00 pre_open -> is_market_open=False, is_pre_open=True")


def test_pre_open_at_0914_still_excluded():
    """At 09:14 (last minute of pre_open), still not market open."""
    now = _at(9, 14)
    assert is_market_open(now) is False
    assert is_pre_open(now) is True
    print("  PASS: 09:14 (last pre_open min) -> is_market_open=False")


def test_opening_buffer_is_market_open():
    """9:15-9:30 is opening session — should be considered 'open' for trading."""
    now = _at(9, 15)
    assert market_session(now) == "opening"
    assert is_market_open(now) is True
    now = _at(9, 29)
    assert is_market_open(now) is True
    print("  PASS: 09:15-09:29 opening -> is_market_open=True")


def test_regular_session_is_open():
    now = _at(10, 30)
    assert market_session(now) == "regular"
    assert is_market_open(now) is True
    print("  PASS: 10:30 regular -> is_market_open=True")


def test_closing_session_is_open():
    now = _at(15, 10)
    assert market_session(now) == "closing"
    assert is_market_open(now) is True
    print("  PASS: 15:10 closing -> is_market_open=True")


def test_after_close_is_closed():
    now = _at(15, 31)
    assert is_market_open(now) is False
    assert is_pre_open(now) is False
    print("  PASS: 15:31 after close -> is_market_open=False")


def test_weekend_is_closed():
    # 2026-08-22 is a Saturday
    sat = datetime(2026, 8, 22, 10, 0, 0)
    assert is_market_open(sat) is False
    sun = datetime(2026, 8, 23, 10, 0, 0)
    assert is_market_open(sun) is False
    print("  PASS: Sat/Sun -> is_market_open=False")


def test_configurable_market_hours():
    """set_market_hours() should let callers shift the boundaries."""
    # Shift pre_open end to 9:00 (no pre_open)
    set_market_hours({"pre_open_start": "8:30", "pre_open_end": "8:45"})
    try:
        # Now 9:00 is in opening (9:00 >= pre_open_end of 8:45) — wait, 9:00 < 9:15 default
        # So 9:00 should now be "opening", not "pre_open"
        now = _at(9, 0)
        s = market_session(now)
        assert s == "opening", f"expected opening after override, got {s}"
        assert is_market_open(now) is True
        assert is_pre_open(now) is False
        print("  PASS: set_market_hours override shifts boundaries correctly")
    finally:
        # Reset to defaults
        set_market_hours({})


if __name__ == "__main__":
    tests = [
        test_pre_open_excluded_from_market_open,
        test_pre_open_at_0914_still_excluded,
        test_opening_buffer_is_market_open,
        test_regular_session_is_open,
        test_closing_session_is_open,
        test_after_close_is_closed,
        test_weekend_is_closed,
        test_configurable_market_hours,
    ]
    failed = 0
    for t in tests:
        print(f"\n{t.__name__}:")
        try:
            t()
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed += 1
        except Exception as e:
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(0 if failed == 0 else 1)
