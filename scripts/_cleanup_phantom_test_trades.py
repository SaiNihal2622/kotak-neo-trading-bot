"""_cleanup_phantom_test_trades.py - close self-test trades that were never closed.

FIX 2026-09-07 12:48: the _self_test_orders.py script had a bug where it
opened trades via order_mgr.execute_plan() but only closed the broker
positions via broker.place_order(). The trade record (order_mgr._trades)
stayed open with closed_at=None, accumulating 5 phantom open positions
over multiple self-test runs. With MAX_OPEN_POSITIONS=2, the bot was
blocked from placing ANY new entries.

This script marks all such phantom trades as closed in order_mgr. Idempotent.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kotak_bot.execution.order_manager import OrderManager
from kotak_bot.broker.paper_client import PaperClient


def main():
    broker = PaperClient()
    broker.connect()
    order_mgr = OrderManager(broker)
    order_mgr._load_state()
    n_total = len(order_mgr._trades)
    n_open_before = len(order_mgr.open_trades())
    print(f"OrderManager loaded: {n_total} trades, {n_open_before} open")

    # Find trades that are 'open' but whose broker position is already closed
    # (i.e. self-test trades that never got marked closed)
    broker_pos = broker.get_positions() if hasattr(broker, 'get_positions') else []
    broker_syms = {p.symbol for p in broker_pos if p.qty != 0}
    print(f"Broker currently has {len(broker_pos)} positions")

    closed_count = 0
    for trade in list(order_mgr.open_trades()):
        # Check if any of this trade's orders are still in the broker
        order_syms = {o.symbol for o in (trade.orders or []) if getattr(o, 'status', None) and o.status.value == "complete"}
        if not order_syms:
            # No filled orders -> never executed, safe to close
            order_mgr.close_trade(trade.trade_id, reason="cleanup: never executed")
            closed_count += 1
            print(f"  closed (no fills): {trade.trade_id} plan={trade.plan.reason[:50]}")
            continue
        if not order_syms & broker_syms:
            # All filled orders are NOT in the broker -> already closed
            order_mgr.close_trade(trade.trade_id, reason="cleanup: position gone from broker")
            closed_count += 1
            print(f"  closed (no broker pos): {trade.trade_id} plan={trade.plan.reason[:50]}")
            continue
        # Trade has an active broker position
        if trade.plan.reason and "self-test" in trade.plan.reason.lower():
            # It's a self-test trade with an active broker position
            # Force-close via broker
            from kotak_bot.broker import Order, OrderSide, OrderType, ProductType
            for o in trade.orders or []:
                if o.status.value == "complete":
                    close_side = OrderSide.SELL if o.side.value == "BUY" else OrderSide.BUY
                    close_ord = Order(
                        symbol=o.symbol, side=close_side, qty=o.qty,
                        order_type=OrderType.MARKET, product=ProductType.MIS,
                        price=0.0, tag="CLEANUP-PHANTOM-TEST",
                    )
                    res = broker.place_order(close_ord)
                    print(f"  broker-closed: {o.symbol} status={res.status.value}")
            order_mgr.close_trade(trade.trade_id, reason="cleanup: self-test trade with broker position")
            closed_count += 1

    # Force-save state
    order_mgr._save_state()
    n_open_after = len(order_mgr.open_trades())
    print(f"\nClosed {closed_count} phantom test trades")
    print(f"Open trades: {n_open_before} -> {n_open_after}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
