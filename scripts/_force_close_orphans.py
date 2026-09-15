"""Force-close orphan positions in the broker that aren't in order_mgr.

These are positions created by the system enforcement or anti-template
that didn't get registered with order_mgr. Force-close them directly
via the broker.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kotak_bot.broker.paper_client import PaperClient
from kotak_bot.execution.order_manager import OrderManager
from kotak_bot.broker import Order, OrderSide, OrderType, ProductType

broker = PaperClient()
broker.connect()
oms = OrderManager(broker)
oms._load_state()

# Get all broker positions
positions = broker.get_positions()
open_broker = [p for p in positions if p.qty != 0]
print(f"Broker positions: {len(open_broker)}")

# Get order_mgr open trades
oms_open = oms.open_trades()
oms_syms = set()
for t in oms_open:
    for o in t.orders or []:
        if getattr(o, "status", None) and o.status.value == "complete":
            oms_syms.add(o.symbol)

# Find orphan positions (in broker but not in order_mgr)
closed = 0
for p in open_broker:
    if p.symbol in oms_syms:
        continue
    # This is an orphan — close it
    close_side = OrderSide.SELL if p.qty > 0 else OrderSide.BUY
    qty = abs(p.qty)
    close_ord = Order(
        symbol=p.symbol,
        side=close_side,
        qty=qty,
        order_type=OrderType.MARKET,
        product=ProductType.MIS,
        price=0.0,
        tag="FORCE-CLOSE-ORPHAN",
    )
    res = broker.place_order(close_ord)
    print(f"  ORPHAN CLOSED: {p.symbol} {close_side.value} qty={qty} status={res.status.value} fill={res.avg_fill_price}")
    closed += 1

print(f"\nClosed {closed} orphan positions")
