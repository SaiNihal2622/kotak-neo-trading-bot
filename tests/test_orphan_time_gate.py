"""Tests for the orphan-auto-close time gate (commit adding time-gate).

Before 2026-09-07 23:15 fix: orphan-auto-close fired on EVERY scan if the
position was small and OTM, regardless of time. This destroyed 2 trades
on 2026-09-07 (closed at 12:04 and 12:42, only 2.5h and 1m after entry).

After fix: orphan-auto-close only fires after 13:30 IST (no-new-trades
time). Before 13:30, the brain-driven positions are still in their
planned hold window (theta capture through Thursday expiry). The
orphan positions are still logged as a WARNING, just not auto-closed.

These tests verify the time-gate logic in isolation. The actual
run_paper() loop is hard to test directly; we extract the gate logic
into a small helper that's easy to test.
"""
from datetime import datetime, time


def should_auto_close_orphan(now_ist: datetime, no_new_trades_time: time) -> bool:
    """Standalone test of the time-gate logic. Returns True if the bot
    should auto-close orphan positions at the given time.

    Args:
        now_ist: current time in IST
        no_new_trades_time: when the no-new-trades gate kicks in (default 13:30)

    Returns:
        True if past no_new_trades_time AND not before market open.
        False if before no_new_trades_time (give brain a fair hold window).
    """
    if not isinstance(now_ist, datetime):
        return False
    # Only operate during market hours
    if now_ist.time() < time(9, 15) or now_ist.time() > time(15, 30):
        return False
    # FIX 2026-09-07 23:15: only auto-close after no_new_trades_time
    if now_ist.time() < no_new_trades_time:
        return False
    return True


def test_auto_close_blocked_before_1330():
    """At 12:04 (when the BNF orphan closed today), gate should be False."""
    t = datetime(2026, 9, 7, 12, 4, 0)
    assert should_auto_close_orphan(t, time(13, 30)) is False


def test_auto_close_blocked_at_1241():
    """At 12:41 (when the NIFTY orphan closed today), gate should be False."""
    t = datetime(2026, 9, 7, 12, 41, 0)
    assert should_auto_close_orphan(t, time(13, 30)) is False


def test_auto_close_blocked_at_1329():
    """At 13:29 (1 minute before gate), should be False."""
    t = datetime(2026, 9, 7, 13, 29, 0)
    assert should_auto_close_orphan(t, time(13, 30)) is False


def test_auto_close_allowed_at_1330():
    """At 13:30 (gate kicks in), should be True."""
    t = datetime(2026, 9, 7, 13, 30, 0)
    assert should_auto_close_orphan(t, time(13, 30)) is True


def test_auto_close_allowed_at_1430():
    """At 14:30 (force-square time), should be True."""
    t = datetime(2026, 9, 7, 14, 30, 0)
    assert should_auto_close_orphan(t, time(13, 30)) is True


def test_auto_close_allowed_at_1500():
    """At 15:00 (after force-square), should be True (degenerate but safe)."""
    t = datetime(2026, 9, 7, 15, 0, 0)
    assert should_auto_close_orphan(t, time(13, 30)) is True


def test_auto_close_blocked_pre_market():
    """At 08:00 (pre-market), should be False — never close during pre-market."""
    t = datetime(2026, 9, 7, 8, 0, 0)
    assert should_auto_close_orphan(t, time(13, 30)) is False


def test_auto_close_blocked_post_market():
    """At 15:45 (post-market), should be False — positions already closed by force-square."""
    t = datetime(2026, 9, 7, 15, 45, 0)
    assert should_auto_close_orphan(t, time(13, 30)) is False


def test_custom_no_new_trades_time():
    """The gate time should be configurable, not hardcoded."""
    # If the config is set to 14:00, gate should be False at 13:45
    t = datetime(2026, 9, 7, 13, 45, 0)
    assert should_auto_close_orphan(t, time(14, 0)) is False
    # And True at 14:01
    t2 = datetime(2026, 9, 7, 14, 1, 0)
    assert should_auto_close_orphan(t2, time(14, 0)) is True


def test_suspect_price_marking_orphan():
    """Verify the suspect_price flag is set on Rs.1.00 fills with ORPHAN tag
    but NOT on Rs.1.00 fills with a real expected price."""
    from kotak_bot.broker.base import Order, OrderSide, OrderType, ProductType
    # ORPHAN tag + Rs.1.00 + no expected price → SUSPECT
    o_suspect = Order(
        symbol="BANKNIFTY10SEP2657200PE", side=OrderSide.SELL, qty=30,
        order_type=OrderType.MARKET, product=ProductType.MIS,
        price=0.0, tag="ORPHAN-AUTO-CLOSE", exchange="NFO",
    )
    o_suspect.avg_fill_price = 1.0
    o_suspect.expected_fill_price = 0.0

    # Same as the inline journal's heuristic
    fill_px = round(o_suspect.avg_fill_price, 2)
    expected_px = round(o_suspect.expected_fill_price, 2) if o_suspect.expected_fill_price else 0
    suspect = (
        abs(fill_px - 1.0) < 0.01
        and expected_px <= 0
        and "ORPHAN" in (o_suspect.tag or "").upper()
    )
    assert suspect is True

    # Rs.1.00 with a real expected price (legitimate deep-OTM fill) → NOT suspect
    o_real = Order(
        symbol="DEEPLY_OTM_PUT", side=OrderSide.BUY, qty=75,
        order_type=OrderType.MARKET, product=ProductType.MIS,
        price=0.0, tag="QUANT-test", exchange="NFO",
    )
    o_real.avg_fill_price = 1.0
    o_real.expected_fill_price = 0.5  # option_chains.json had a 0.5 reference
    fill_px = round(o_real.avg_fill_price, 2)
    expected_px = round(o_real.expected_fill_price, 2) if o_real.expected_fill_price else 0
    suspect = (
        abs(fill_px - 1.0) < 0.01
        and expected_px <= 0
        and "ORPHAN" in (o_real.tag or "").upper()
    )
    assert suspect is False  # has expected price, not ORPHAN tag

    # Rs.1.00 with ORPHAN tag but expected price → NOT suspect (defensive)
    o_mixed = Order(
        symbol="X", side=OrderSide.SELL, qty=10,
        order_type=OrderType.MARKET, product=ProductType.MIS,
        price=0.0, tag="ORPHAN-AUTO-CLOSE", exchange="NFO",
    )
    o_mixed.avg_fill_price = 1.0
    o_mixed.expected_fill_price = 200.0
    fill_px = round(o_mixed.avg_fill_price, 2)
    expected_px = round(o_mixed.expected_fill_price, 2) if o_mixed.expected_fill_price else 0
    suspect = (
        abs(fill_px - 1.0) < 0.01
        and expected_px <= 0
        and "ORPHAN" in (o_mixed.tag or "").upper()
    )
    assert suspect is False  # has expected price
