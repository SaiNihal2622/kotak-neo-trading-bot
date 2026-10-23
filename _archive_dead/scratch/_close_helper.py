"""Force-close all positions via PaperClient."""
import sys
sys.path.insert(0, '.')
from kotak_bot.broker.paper_client import PaperClient
from kotak_bot.broker.base import Order, OrderType, OrderSide, ProductType

pc = PaperClient(fill_mode='realistic')
pc.connect()

print(f"Positions: {len(pc._positions)}")
for sym, pos in pc._positions.items():
    print(f"  {sym}: qty={pos.qty} exchange={pos.exchange}")

print()
print("Closing all positions at MARKET...")
closed = 0
for sym, pos in list(pc._positions.items()):
    if pos.qty == 0:
        continue
    close_side = OrderSide.SELL if pos.qty > 0 else OrderSide.BUY
    o = Order(
        symbol=sym,
        side=close_side,
        qty=abs(pos.qty),
        order_type=OrderType.MARKET,
        product=ProductType.MIS,
        price=0.0,
        tag='MAVIS-FORCE-CLOSE',
        exchange=pos.exchange,
        strike=pos.strike,
        option_type=pos.option_type,
        expiry=pos.expiry,
        underlying=getattr(pos, 'underlying', 'NIFTY'),
    )
    res = pc.place_order(o)
    print(f"  {sym}: {close_side.value} {abs(pos.qty)} → status={res.status.value} fill={res.avg_fill_price}")
    if res.status.value in ('complete', 'filled'):
        closed += 1

print(f"\nClosed {closed} positions")
print(f"Remaining: {len(pc._positions)}")