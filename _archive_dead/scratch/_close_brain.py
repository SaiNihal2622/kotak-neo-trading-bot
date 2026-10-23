"""Close all open positions via PaperClient (no position cap)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, '.')

# Read positions
state_path = Path('data_cache/paper_state.json')
state = json.loads(state_path.read_text(encoding='utf-8'))
positions = state.get('positions', {})
print(f"Found {len(positions)} positions to close")

# Use a fresh PaperClient
from kotak_bot.broker.paper_client import PaperClient
from kotak_bot.broker.base import Order, OrderType, OrderSide, ProductType

pc = PaperClient(fill_mode='realistic')
pc.connect()

closed_count = 0
total_pnl = 0
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
        underlying=getattr(pos, 'underlying', 'NIFTY') or 'NIFTY',
    )
    res = pc.place_order(o)
    fill_price = res.avg_fill_price or 0
    pnl = (fill_price - pos.avg_price) * pos.qty * (-1 if pos.qty < 0 else 1)
    total_pnl += pnl
    print(f"  {sym}: {close_side.value} {abs(pos.qty)} fill={fill_price} pnl={pnl:+.0f} status={res.status.value}")
    if res.status.value in ('complete', 'filled'):
        closed_count += 1

print(f"\nClosed {closed_count} positions, total realized P&L from closes: {total_pnl:+.0f}")
print(f"Final state: {len(pc._positions)} open positions")