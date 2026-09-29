"""Tests for the LiveFeed → PaperClient tick wiring (Fix A, 2026-09-29).

The 2026-09-29 broken-condor was partly caused by PaperClient having 0 ticks
despite LiveFeed seeing 148 ticks. The SELL LIMIT auto-snap needs bid data;
without it, SELL orders sat at limit=113 while bid=12 and timed out at 60s.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestTickInjection:
    """LiveFeed must inject ticks to PaperClient so SELL LIMIT snap can fire."""

    def test_dispatch_injects_tick_to_broker(self):
        """A tick dispatched by LiveFeed must reach PaperClient._ticks."""
        from kotak_bot.data.live_feed import LiveFeed, Tick
        from kotak_bot.broker.paper_client import PaperClient

        broker = PaperClient(fill_mode='realistic')
        broker.connect()
        feed = LiveFeed(mode='synthetic', broker=broker)
        feed.start()

        tick = Tick(symbol='NIFTY', ltp=22750.0, bid=22749.0, ask=22751.0,
                    exchange='NSE')
        feed._dispatch(tick)
        # Give lock a moment
        import time
        time.sleep(0.05)

        assert 'NIFTY' in broker._ticks, (
            f"After dispatch, broker._ticks must contain 'NIFTY'. "
            f"Got: {list(broker._ticks.keys())}"
        )
        assert broker._ticks['NIFTY'].ltp == 22750.0

    def test_dispatch_with_no_broker_logs_warning(self):
        """LiveFeed with broker=None must log a one-time warning, not silently fail."""
        from kotak_bot.data.live_feed import LiveFeed, Tick
        feed = LiveFeed(mode='synthetic', broker=None)
        # Force a dispatch
        tick = Tick(symbol='NIFTY', ltp=22750.0, bid=22749.0, ask=22751.0,
                    exchange='NSE')
        # Should not raise
        feed._dispatch(tick)
        # Should have set the warned flag
        assert getattr(feed, '_warned_no_broker', False), (
            "LiveFeed with no broker must set _warned_no_broker=True after first dispatch"
        )

    def test_set_broker_late_binding_replays_ticks(self):
        """set_broker() must replay cached ticks so the new broker gets bid/ask data."""
        from kotak_bot.data.live_feed import LiveFeed, Tick
        from kotak_bot.broker.paper_client import PaperClient

        broker1 = PaperClient(fill_mode='realistic')
        broker1.connect()
        feed = LiveFeed(mode='synthetic', broker=None)

        # Dispatch some ticks (they go to feed._latest but not broker1)
        for i in range(3):
            tick = Tick(symbol='NIFTY', ltp=22750 + i, bid=22749 + i,
                        ask=22751 + i, exchange='NSE')
            feed._dispatch(tick)
        # 0 ticks should be in broker1
        assert 'NIFTY' not in broker1._ticks, (
            "Without broker set, ticks should not be in broker1._ticks"
        )

        # Now set the broker — it should get the cached ticks
        feed.set_broker(broker1)
        assert 'NIFTY' in broker1._ticks, (
            "set_broker() must replay cached ticks to the new broker"
        )
        assert broker1._ticks['NIFTY'].ltp == 22752  # last tick value


class TestSELLLimitSnapRequiresTick:
    """The SELL LIMIT snap requires bid data in PaperClient._ticks.

    Without ticks, the snap can't fire and SELL orders sit at wrong limit prices.
    """

    def test_sell_snap_uses_tick_bid(self):
        """When tick exists, snap must fire (bid * 1.05)."""
        from kotak_bot.broker.paper_client import PaperClient
        from kotak_bot.broker.base import Order, OrderType, OrderSide, ProductType, Tick

        pc = PaperClient(fill_mode='realistic')
        pc.connect()
        # Inject a tick with bid=14.30
        pc.inject_tick(Tick(symbol='NIFTY01OCT2622750CE', ltp=14.30,
                            bid=14.30, ask=14.35, exchange='NFO'))
        # Try a SELL LIMIT at 113.0 (way above bid)
        o = Order(
            symbol='NIFTY01OCT2622750CE',
            side=OrderSide.SELL,
            qty=75,
            order_type=OrderType.LIMIT,
            product=ProductType.MIS,
            price=113.0,
            tag='TEST',
            exchange='NFO',
        )
        placed = pc.place_order(o)
        # The snap should have fired: limit was 113, bid=14.30, so new limit=14.30*1.05=15.015 → ~15
        assert placed.price < 50.0, (
            f"SELL LIMIT snap should bring limit to ~15 (bid*1.05), got {placed.price}. "
            f"This means the snap didn't fire — likely due to missing tick data."
        )

    def test_sell_snap_no_tick_no_snap(self):
        """Without a tick, the snap can't fire (defensive — at least limit should remain).
        This is the regression test for the broken-condor scenario: LLM proposes
        limit=113, no tick data, snap doesn't fire, order sits 60s and times out."""
        from kotak_bot.broker.paper_client import PaperClient
        from kotak_bot.broker.base import Order, OrderType, OrderSide, ProductType

        pc = PaperClient(fill_mode='realistic')
        pc.connect()
        # NO inject_tick call — empty _ticks
        o = Order(
            symbol='NIFTY01OCT2622750CE',
            side=OrderSide.SELL,
            qty=75,
            order_type=OrderType.LIMIT,
            product=ProductType.MIS,
            price=113.0,
            tag='TEST',
            exchange='NFO',
        )
        placed = pc.place_order(o)
        # Without tick, the snap CAN'T fire (no bid data). Limit stays at 113.0.
        # This is exactly the broken-condor bug pattern.
        assert placed.price == 113.0, (
            f"Without tick data, SELL LIMIT should remain at 113 (no snap possible). "
            f"Got {placed.price} — if this is much lower, the test is broken."
        )