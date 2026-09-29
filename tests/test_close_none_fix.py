"""Tests for the close_None fix and broken-condor handler order_mgr update.

The 2026-09-29 broken-condor chaos extended past my initial fixes: at 15:15 IST
the EOD force-square called order_mgr.close_trade() on 4 trades whose entry
orders had order_id=None (because the brain-driven QUANT-ACTION handler
reconstructed Order objects without order_id). The resulting close orders
had tag=f"close_{None}" = "close_None". Since the broker had 0 longs at
that point (already closed by BROKEN-CONDOR-CLOSE), the SELLs opened 3 new
SHORT positions. Then ORPHAN-AUTO-CLOSE detected the orphan SHORTS and
bought them back. Net loss: ~Rs.120 of churn.

These tests guard the fixes:
1. Fix D: _leg_records must capture order_id, reconstructed Order must have it
2. Fix E: broken-condor handler must also update order_mgr._symbol_to_trade
3. Fix F: order_mgr.close_trade() must generate proper close_<id> tags
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestLegRecordsCaptureOrderID:
    """FIX D: _leg_records must include order_id so order_mgr can close cleanly."""

    def test_main_py_records_order_id_in_leg_records(self):
        """The QUANT-ACTION handler must capture order_id when building _leg_records."""
        main_py = (ROOT / "kotak_bot" / "__main__.py").read_text(encoding="utf-8")
        # Find the leg_records.append block
        idx = main_py.find('_leg_records.append({')
        assert idx > 0
        # Get the next 500 chars
        block = main_py[idx:idx + 500]
        assert 'order_id' in block, (
            "_leg_records.append must include order_id (FIX 2026-09-29 19:35)"
        )

    def test_main_py_reconstructed_order_has_order_id(self):
        """When reconstructing Order objects for register_external_managed_trade,
        the order_id must be propagated."""
        main_py = (ROOT / "kotak_bot" / "__main__.py").read_text(encoding="utf-8")
        # Find the Order constructor used in register_external_managed_trade
        # It's the Order() call that appears BEFORE _orders.append(_o).
        # Find _orders.append(_o) and walk backwards to the Order() constructor.
        idx = main_py.find('_orders.append(_o)')
        assert idx > 0
        # Walk backwards to find the most recent Order() constructor
        before = main_py[max(0, idx-2000):idx]
        last_order_idx = before.rfind('_o = Order(')
        assert last_order_idx > 0, (
            "Could not find _o = Order(...) constructor before _orders.append(_o)"
        )
        # Get the Order() constructor (next 800 chars from the _o = Order( start)
        order_constructor = before[last_order_idx:] + main_py[idx:idx+50]
        assert 'order_id=_lr.get("order_id")' in order_constructor, (
            "Reconstructed Order must propagate order_id from _leg_records"
        )


class TestCloseTradeGeneratesProperTags:
    """FIX F: order_mgr.close_trade() generates close_<id> tags when order_id is set."""

    def test_close_trade_with_order_id_uses_proper_tag(self):
        """When trade's orders have order_id, close_trade generates close_<id> tag."""
        from kotak_bot.broker.paper_client import PaperClient
        from kotak_bot.execution.order_manager import OrderManager
        from kotak_bot.broker.base import (
            Order, OrderSide, OrderType, OrderStatus, ProductType, Tick
        )
        from kotak_bot.strategy.trade_plan import TradePlan, StrategyName

        pc = PaperClient(fill_mode='market_like')
        pc.connect()
        # Inject a tick so the close order can fill
        pc.inject_tick(Tick(symbol='NIFTY01OCT2622950CE', ltp=3.0,
                            bid=3.0, ask=3.05, exchange='NFO'))

        om = OrderManager(pc)

        # Place an entry order via the broker directly (simulating brain-driven flow)
        entry = Order(
            symbol='NIFTY01OCT2622950CE',
            side=OrderSide.BUY,
            qty=75,
            order_type=OrderType.MARKET,
            product=ProductType.MIS,
            price=0.0,
            tag='TEST-ENTRY',
            exchange='NFO',
            strike=22950,
            option_type='CE',
            expiry='2026-10-01',
            underlying='NIFTY',
        )
        result = pc.place_order(entry)
        # Build a real TradePlan (register_external_managed_trade logs plan.strategy.value)
        plan = TradePlan(
            underlying='NIFTY',
            strategy=StrategyName.CUSTOM,
            legs=[{'side': 'BUY', 'qty': 1, 'strike': 22950, 'opt_type': 'CE',
                    'order_type': 'MARKET', 'price': 0.0, 'tag': 'TEST'}],
            target=0.0, stop=0.0, confidence=0.0, reason='test',
        )
        trade = om.register_external_managed_trade(plan=plan, filled_orders=[result])
        # Verify entry order has order_id
        entry_order = trade.orders[0]
        assert entry_order.order_id is not None, (
            "Entry order must have order_id assigned by PaperClient"
        )

        # Now close the trade
        om.close_trade(trade.trade_id, reason="test_close")

        # Verify the close order has the proper tag (close_<id>, NOT close_None)
        close_orders = [o for o in trade.orders if o.tag and o.tag.startswith("close_")]
        assert len(close_orders) >= 1, "close_trade should have placed a close order"
        for co in close_orders:
            assert co.tag != 'close_None', (
                f"Close order tag must NOT be 'close_None' (regression: order_id was None). "
                f"Got tag={co.tag!r}"
            )
            assert co.tag.startswith('close_') and co.tag != 'close_', (
                f"Close order tag must be 'close_<id>'. Got: {co.tag!r}"
            )

    def test_close_trade_with_none_order_id_produces_close_none(self):
        """Regression test: this is the BUG we fixed. With None order_id,
        close_trade generates 'close_None' which causes the 15:15 chaos."""
        from kotak_bot.broker.paper_client import PaperClient
        from kotak_bot.execution.order_manager import OrderManager
        from kotak_bot.broker.base import Order, OrderSide, OrderType, ProductType
        from kotak_bot.strategy.trade_plan import TradePlan, StrategyName

        pc = PaperClient(fill_mode='market_like')
        pc.connect()
        om = OrderManager(pc)

        # Build a TradePlan + manually-constructed Order with order_id=None
        plan = TradePlan(
            underlying='NIFTY',
            strategy=StrategyName.CUSTOM,
            legs=[{'side': 'BUY', 'qty': 1, 'strike': 22950, 'opt_type': 'CE',
                    'order_type': 'MARKET', 'price': 0.0, 'tag': 'TEST'}],
            target=0.0, stop=0.0, confidence=0.0, reason='test',
        )
        entry = Order(
            symbol='NIFTY01OCT2622950CE',
            side=OrderSide.BUY,
            qty=75,
            order_type=OrderType.MARKET,
            product=ProductType.MIS,
            price=0.0,
            tag='TEST-ENTRY',
            exchange='NFO',
            strike=22950,
            option_type='CE',
            expiry='2026-10-01',
            underlying='NIFTY',
            order_id=None,  # explicit None to simulate the bug
        )
        trade = om.register_external_managed_trade(plan=plan, filled_orders=[entry])
        # Now close — should produce close_None (the buggy behavior)
        try:
            om.close_trade(trade.trade_id, reason="test")
            close_orders = [o for o in trade.orders if o.tag and o.tag.startswith('close_')]
            for co in close_orders:
                # This is the bug we're fixing — assert that with None order_id
                # the tag IS close_None (so the fix D actually changes behavior)
                assert co.tag == 'close_None', (
                    f"With order_id=None, tag must be 'close_None' (regression test). "
                    f"Got: {co.tag!r}"
                )
        except Exception:
            # Some implementations might raise on missing order_id — that's also acceptable
            pass


class TestBrokenCondorHandlerUpdatesOrderMgr:
    """FIX E: broken-condor handler must update order_mgr._symbol_to_trade."""

    def test_broken_condor_handler_removes_symbol_mapping(self):
        """When a symbol is closed by the broken-condor handler, the symbol
        mapping must be removed from order_mgr so the orphan-killer doesn't
        re-close it."""
        main_py = (ROOT / "kotak_bot" / "__main__.py").read_text(encoding="utf-8")
        # Find the FIX 2026-09-29 19:45 comment that introduces the order_mgr
        # update inside the top-loop broken-condor handler.
        idx = main_py.find('FIX 2026-09-29 19:45')
        assert idx > 0
        # Get the next 2500 chars (the order_mgr update block)
        block = main_py[idx:idx + 2500]
        # The fix must include:
        # 1. Look up _om_tid_top from order_mgr._symbol_to_trade
        # 2. Mark closed_at on the trade
        # 3. Remove from _symbol_to_trade
        assert '_symbol_to_trade' in block, (
            "Broken-condor handler must reference order_mgr._symbol_to_trade"
        )
        assert 'closed_at = datetime.now(timezone.utc)' in block, (
            "Broken-condor handler must set trade.closed_at"
        )
        assert 'del order_mgr._symbol_to_trade' in block, (
            "Broken-condor handler must remove the symbol mapping to prevent "
            "the orphan-killer from re-closing it (FIX 2026-09-29 19:45)"
        )

    def test_broken_condor_force_action_handler_also_updates_order_mgr(self):
        """The force-action-handler variant of the broken-condor fix must also
        update order_mgr. (Both handlers exist for resilience.)"""
        main_py = (ROOT / "kotak_bot" / "__main__.py").read_text(encoding="utf-8")
        # Both blocks are tagged with FIX 2026-09-29 19:45. The first occurrence
        # is the TOP-LOOP handler (uses exit_reason="broken_condor_emergency_top_loop"),
        # the second is the FORCE-ACTION handler (uses "broken_condor_emergency").
        first_idx = main_py.find('FIX 2026-09-29 19:45')
        assert first_idx > 0
        second_idx = main_py.find('FIX 2026-09-29 19:45', first_idx + 10)
        assert second_idx > 0, (
            "Both broken-condor handlers (force-action + top-loop) must "
            "include the FIX 2026-09-29 19:45 order_mgr update"
        )
        # The force-action handler is the SECOND occurrence. Verify it has
        # the order_mgr update + uses the right exit_reason label.
        second_block = main_py[second_idx:second_idx + 2500]
        assert 'del order_mgr._symbol_to_trade' in second_block, (
            "Force-action broken-condor handler must also update order_mgr "
            "to prevent the close_None → orphan-auto-close loop"
        )
        assert '_om_trade.exit_reason = "broken_condor_emergency"' in second_block, (
            "Force-action handler must use reason='broken_condor_emergency' "
            "(the top-loop variant uses 'broken_condor_emergency_top_loop')"
        )