"""Check fill_mode and snap behavior."""
import sys
sys.path.insert(0, '.')
from kotak_bot.broker.paper_client import PaperClient
from kotak_bot.broker.base import Order, OrderType, OrderSide, ProductType

pc = PaperClient(fill_mode='realistic')
print(f"fill_mode: {pc.fill_mode}")
print(f"'realistic' in fill_mode: {'realistic' in pc.fill_mode}")
# Try a SELL limit that should snap
o = Order(
    symbol='NIFTY01OCT2622750CE',
    side=OrderSide.SELL,
    qty=75,
    order_type=OrderType.LIMIT,
    product=ProductType.MIS,
    price=113.0,
    exchange='NFO',
    strike=22750,
    option_type='CE',
    expiry='2026-10-01',
    underlying='NIFTY',
)
pc.connect()
# Inject a tick with bid=14.3
from kotak_bot.broker.base import Tick
pc._ticks['NIFTY01OCT2622750CE'] = Tick(symbol='NIFTY01OCT2622750CE', bid=14.3, ask=14.35, ltp=14.3, exchange='NFO')
print(f"Before place: order.price = {o.price}")
placed = pc.place_order(o)
print(f"After place: order.price = {placed.price}")
print(f"Order status: {placed.status}")