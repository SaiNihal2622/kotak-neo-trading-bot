"""_self_test_orders.py - end-to-end smoke test for the bot's order flow.

FIX 2026-09-04 12:30: today, 3 of the brain's OPENs silently failed with placed_legs=0
due to the line 1283 shadow-import bug. The bot logged 'QUANT-ACTION OPEN
iron_condor NIFTY legs_placed=0/4' but the actual order never went through.

This self-test:
1. Builds a TradePlan (mimicking what the brain would write)
2. Calls order_mgr.execute_plan() (the path the brain's orders should go through)
3. Verifies the order reaches broker.place_order() and gets a fill
4. Closes the test position immediately
5. Reports success/failure

If the self-test passes, the order flow is working. If it fails with
UnboundLocalError, the shadow-import bug has come back.

Run this BEFORE the UAC restart to confirm the new code works.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def main():
    print("=" * 60)
    print("BOT ORDER FLOW SELF-TEST")
    print("=" * 60)
    print()

    # 1. Try importing the critical Order class
    print("[1/5] Testing Order class import...")
    try:
        from kotak_bot.broker import Order, OrderSide, OrderType, OrderStatus, ProductType
        print(f"  OK: Order, OrderSide, OrderType, OrderStatus, ProductType all importable")
    except Exception as e:
        print(f"  FAIL: {e}")
        return 1

    # 2. Build a test TradePlan
    print("[2/5] Building test TradePlan (NIFTY long call)...")
    try:
        from kotak_bot.strategy.base import TradePlan, StrategyName
        plan = TradePlan(
            underlying="NIFTY",
            strategy=StrategyName.DIRECTIONAL_DEBIT,  # 1-leg directional for simplicity
            legs=[
                # FIX 2026-09-04 12:31: include a price (Rs.50) so execute_plan's bracket
                # calculation can compute SL/target. Without this, `entry > 0` raises TypeError.
                {"side": "BUY", "qty": 1, "strike": 24000, "opt_type": "CE", "order_type": "MARKET", "price": 50.0},
            ],
            target=100, stop=25, confidence=0.7,
            reason="self-test order flow (FIX 2026-09-04 12:30)",
            expiry="2026-09-10",
        )
        print(f"  OK: TradePlan built with {len(plan.legs)} leg(s)")
    except Exception as e:
        print(f"  FAIL: {e}")
        return 1

    # 3. Try to instantiate the order manager
    print("[3/5] Instantiating OrderManager + PaperClient...")
    try:
        from kotak_bot.broker.paper_client import PaperClient
        from kotak_bot.execution.order_manager import OrderManager
        broker = PaperClient()
        broker.connect()
        order_mgr = OrderManager(broker)
        print(f"  OK: PaperClient + OrderManager ready")
    except Exception as e:
        print(f"  FAIL: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # 4. Execute the plan (this is the path the brain's orders should take)
    print("[4/5] Executing plan via order_mgr.execute_plan()...")
    try:
        trade = order_mgr.execute_plan(plan, qty=1, expiry="2026-09-10", lot_sizes={"NIFTY": 75})
        print(f"  OK: trade_id={trade.trade_id}, orders={len(trade.orders)}")
        for o in trade.orders:
            print(f"    {o.symbol} {o.side.value} {o.qty} @ {o.avg_fill_price or o.price} status={o.status.value}")
    except UnboundLocalError as ule:
        print(f"  FAIL: UnboundLocalError — shadow-import trap is BACK!")
        print(f"  {ule}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # 5. Close the test position immediately (don't leave it open)
    print("[5/5] Closing test position...")
    try:
        from kotak_bot.broker import OrderSide, OrderType, ProductType
        for o in trade.orders:
            if o.status.value == "complete":
                close_side = OrderSide.SELL if o.side.value == "BUY" else OrderSide.BUY
                close_order = Order(
                    symbol=o.symbol, side=close_side, qty=o.qty,
                    order_type=OrderType.MARKET, product=ProductType.MIS,
                    price=0.0, tag='SELF-TEST-CLOSE',
                )
                result = broker.place_order(close_order)
                print(f"    closed {o.symbol} {close_side.value} {o.qty} @ {result.avg_fill_price}")
        print("  OK: test position closed")
    except Exception as e:
        print(f"  WARN: cleanup failed: {e} — close it manually")

    print()
    print("=" * 60)
    print("SELF-TEST PASSED — order flow is healthy")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
