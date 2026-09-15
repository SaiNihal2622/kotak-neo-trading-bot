"""Debug: dump the 5 OPEN trades that are blocking new entries."""
import sys
sys.path.insert(0, r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot")
from kotak_bot.execution.order_manager import OrderManager

m = OrderManager(broker=None)
m._load_state()
print(f"total trades: {len(m._trades)}")
print(f"open trades: {len(m.open_trades())}")
print()
print("=== OPEN TRADES (blocking new entries) ===")
for i, t in enumerate(m.open_trades()):
    print(f"\n[{i+1}] trade_id={t.trade_id}")
    print(f"    status: {t.status}")
    print(f"    opened_at: {t.opened_at}")
    print(f"    closed_at: {t.closed_at}")
    print(f"    plan: {t.plan}")
    print(f"    orders: {len(t.orders) if t.orders else 0}")
    for o in (t.orders or []):
        print(f"      order {o.order_id}: {o.symbol} {o.side} qty={o.qty} status={o.status}")
