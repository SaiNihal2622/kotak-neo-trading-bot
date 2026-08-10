"""Close all naked/orphan positions in paper broker.

CONTEXT: After rebuilding positions from order history, the 08:39 and 08:48
iron condors have their LONG wings gone (closed by an earlier startup_reconcile
at 09:26:33 that SELL'd the long wings in chunks of 150/60). The SHORT wings
remain as naked shorts. This script BUYs back those shorts to flatten.

Safe to run: only operates on existing positions, places MARKET close orders.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kotak_bot.broker.paper_client import PaperClient
from kotak_bot.broker.base import Order, OrderSide, OrderType, ProductType

pc = PaperClient(
    starting_capital=100_000.0,
    persist_path=str(ROOT / "data_cache" / "paper_state.json"),
)
pc.connect()

positions = pc.get_positions()
print(f"Found {len(positions)} open positions:")
for p in positions:
    print(f"  {p.symbol:30s}  qty={p.qty:+d}  avg={p.avg_price:.2f}  ltp={p.ltp:.2f}")

if not positions:
    print("Nothing to close.")
    pc.disconnect()
    sys.exit(0)

print("\nPlacing close orders...")
for p in positions:
    # close a position by flipping side
    close_side = OrderSide.SELL if p.qty > 0 else OrderSide.BUY
    close_qty = abs(p.qty)
    close_order = Order(
        symbol=p.symbol,
        side=close_side,
        qty=close_qty,
        order_type=OrderType.MARKET,
        product=p.product,
        tag="orphan_close",
        exchange=p.exchange,
        strike=p.strike,
        option_type=p.option_type,
        expiry=p.expiry,
        underlying=p.underlying,
    )
    pc.place_order(close_order)

# wait a moment for fills
import time
time.sleep(2)

# report new state
positions = pc.get_positions()
margins = pc.get_margins()
print(f"\nAfter close:")
print(f"  Positions: {len(positions)}")
for p in positions:
    print(f"  {p.symbol:30s}  qty={p.qty:+d}  pnl=Rs.{p.pnl:,.0f}")
print(f"  Cash:           Rs.{margins['available']:,.0f}")
print(f"  Realized PnL:   Rs.{margins['realized_pnl']:,.0f}")
print(f"  Unrealized PnL: Rs.{margins['unrealized_pnl']:,.0f}")

pc.disconnect()
