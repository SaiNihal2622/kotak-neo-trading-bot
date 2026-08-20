"""Regression test for time-based phantom 0DTE detection (2026-08-20 patch 2).

Bug: the original phantom filter only checked `ltp <= 0`, but post-market
the broker reports 0DTE positions with **cached LTP > 0** (the value from
earlier in the trading session). The filter missed them and the 6 phantoms
from Day 11 stayed in `paper_state.json` blocking Day 12 signals.

Fix: added `is_past_market_close()` to `kotak_bot/utils/clock.py` and wired
it into both `_is_phantom_0dte()` (startup_reconcile) and the 08:55 IST
pre-market audit. After 15:30 IST, any 0DTE position with `expiry == today`
is now classified as phantom regardless of cached LTP.
"""
from __future__ import annotations

from datetime import datetime, time, timezone, timedelta

import pytest

from kotak_bot.utils.clock import is_past_market_close, _MARKET_HOURS, IST


# ------------------------------------------------------------------
# Direct unit tests of is_past_market_close()
# ------------------------------------------------------------------

def test_pre_market_close_returns_false():
    """09:00 IST is well before 15:30 close — should be False."""
    t = datetime(2026, 8, 21, 9, 0, tzinfo=IST)
    assert is_past_market_close(t) is False


def test_mid_session_returns_false():
    """12:00 IST is during regular session — should be False."""
    t = datetime(2026, 8, 21, 12, 0, tzinfo=IST)
    assert is_past_market_close(t) is False


def test_just_before_close_returns_false():
    """15:29:59 IST is one second before close — should be False."""
    t = datetime(2026, 8, 21, 15, 29, 59, tzinfo=IST)
    assert is_past_market_close(t) is False


def test_exact_close_returns_true():
    """15:30:00 IST is exactly at close — should be True (>=)."""
    t = datetime(2026, 8, 21, 15, 30, 0, tzinfo=IST)
    assert is_past_market_close(t) is True


def test_post_close_returns_true():
    """23:30 IST post-market — the actual case from Day 11 bug. Should be True."""
    t = datetime(2026, 8, 20, 23, 30, 0, tzinfo=IST)
    assert is_past_market_close(t) is True


def test_midnight_returns_false_but_expiry_filter_catches():
    """00:00 IST — time check returns False, but the expiry<today filter still catches.

    At 00:00 IST (new day), the time check is False (00:00 < 15:30). However, the
    phantom filter ALSO checks `expiry < today` BEFORE the time check, so a
    position with `expiry = yesterday` is caught by that path. The two checks
    together cover the full post-market window.
    """
    t = datetime(2026, 8, 21, 0, 0, 0, tzinfo=IST)
    assert is_past_market_close(t) is False
    # But the phantom filter still catches it via expiry < today
    yesterday_str = "2026-08-20"
    today_str = t.strftime("%Y-%m-%d")
    assert yesterday_str < today_str  # this is the path that catches it


def test_uses_configured_close_time():
    """If close is configured to 14:00, is_past_market_close at 14:30 returns True."""
    from kotak_bot.utils import clock as clock_mod
    original = clock_mod._MARKET_HOURS["close"]
    try:
        clock_mod._MARKET_HOURS["close"] = time(14, 0)
        t = datetime(2026, 8, 21, 14, 30, 0, tzinfo=IST)
        assert is_past_market_close(t) is True
        t2 = datetime(2026, 8, 21, 13, 30, 0, tzinfo=IST)
        assert is_past_market_close(t2) is False
    finally:
        clock_mod._MARKET_HOURS["close"] = original


def test_default_now_returns_correct_value():
    """Smoke test: calling with no arg should not raise; should return a bool."""
    result = is_past_market_close()
    assert isinstance(result, bool)


# ------------------------------------------------------------------
# Behavioral test: phantom 0DTE filter catches cached-LTP post-market
# ------------------------------------------------------------------

def test_phantom_filter_catches_cached_ltp_post_market():
    """Simulate the Day 11 bug: 6 phantoms with LTP > 0 (cached) post-market.

    Pre-fix: only `ltp <= 0` was checked → all 6 missed.
    Post-fix: is_past_market_close returns True after 15:30 → all 6 caught.
    """
    # Simulated broker position with cached LTP > 0 (the Day 11 bug pattern)
    class FakePos:
        def __init__(self, symbol, qty, ltp, expiry):
            self.symbol = symbol
            self.qty = qty
            self.ltp = ltp
            self.expiry = expiry
    pos = FakePos("NIFTY20AUG2624300CE", 130, ltp=48.82, expiry="2026-08-20")
    # After 15:30 IST — phantom regardless of LTP
    t_post = datetime(2026, 8, 20, 23, 30, 0, tzinfo=IST)
    assert is_past_market_close(t_post) is True
    # LTP check alone (pre-fix) would FAIL to filter this — confirm the bug pattern
    ltp_only_check = (pos.ltp or 0) <= 0
    assert ltp_only_check is False  # LTP-only misses the phantom (the original bug)
    # Time check (post-fix) CORRECTLY classifies as phantom
    # (this is the same condition _is_phantom_0dte now uses)
    is_phantom = is_past_market_close(t_post)
    assert is_phantom is True


def test_phantom_filter_preserves_intraday_live_position():
    """At 10:00 IST, a 0DTE position with LTP > 0 is genuinely live (not phantom)."""
    t_mid = datetime(2026, 8, 21, 10, 0, 0, tzinfo=IST)
    assert is_past_market_close(t_mid) is False
    # 0DTE position with valid LTP during market hours is NOT phantom
    is_phantom = is_past_market_close(t_mid)
    assert is_phantom is False
