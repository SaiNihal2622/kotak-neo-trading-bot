"""Check fills in the running paper state."""
import sys
sys.path.insert(0, '.')

from kotak_bot.broker.paper_client import PaperClient
p = PaperClient(persist_path='data_cache/paper_state.json')
p.connect()
print(f'Orders: {len(p._orders)}, Positions: {len(p._positions)}')
for oid, o in p._orders.items():
    s = str(o.status)
    if "OrderStatus" in s:
        s = s.split(".")[-1]
    print(f'  {oid[:20]} {o.symbol:30s} side={o.side.value if hasattr(o.side, "value") else o.side} status={s} filled={o.filled_qty} @ {o.avg_fill_price}')
print(f'\nPositions:')
for sym, pos in p._positions.items():
    print(f'  {sym}: qty={pos.qty} avg={pos.avg_price:.2f} ltp={pos.ltp:.2f} pnl=Rs.{pos.pnl:.2f}')
