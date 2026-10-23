"""Check OrderType/OrderSide enum behavior."""
import sys
sys.path.insert(0, '.')
from kotak_bot.broker.base import OrderType, OrderSide
print(f"OrderType.LIMIT = {OrderType.LIMIT!r}")
print(f"OrderType.LIMIT == 'LIMIT': {OrderType.LIMIT == 'LIMIT'}")
print(f"OrderSide.SELL = {OrderSide.SELL!r}")
print(f"OrderSide.SELL == 'SELL': {OrderSide.SELL == 'SELL'}")
print(f"OrderType.MARKET = {OrderType.MARKET!r}")
print(f"OrderType.MARKET == 'MARKET': {OrderType.MARKET == 'MARKET'}")