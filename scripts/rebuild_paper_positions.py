"""One-shot recovery: rebuild paper positions from COMPLETE order history.

BEFORE FIX: PaperClient._apply_fill SELL branch only mutated existing positions.
If you SELL into an empty book (iron butterfly, strangle, etc.), the SHORT was
silently lost from positions. The later close-BUY created a phantom LONG.

This script runs `PaperClient.rebuild_positions_from_orders()` which walks the
order book and recomputes the net position per symbol from scratch.

Usage (from project root, venv active):
    python scripts/rebuild_paper_positions.py
"""
import sys
from pathlib import Path

# project root on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kotak_bot.broker.paper_client import PaperClient  # noqa: E402

pc = PaperClient(
    starting_capital=100_000.0,
    persist_path=str(ROOT / "data_cache" / "paper_state.json"),
)
print(f"Capital before: Rs.{pc._cash:,.2f}")
print(f"Realized before: Rs.{pc._realized_pnl:,.2f}")
print(f"Positions before: {len(pc._positions)}")
for s, p in pc._positions.items():
    print(f"  {s:30s}  qty={p.qty:+d}  avg={p.avg_price:.2f}  ltp={p.ltp:.2f}  pnl=Rs.{p.pnl:,.0f}")

print("\n--- rebuild_positions_from_orders() ---")
report = pc.rebuild_positions_from_orders()
print(f"  before_count: {report['before_count']}")
print(f"  after_count:  {report['after_count']}")
print(f"  realized_pnl delta: Rs.{report['realized_pnl_delta']:,.2f}")

print("\nPositions after:")
for s, p in pc._positions.items():
    print(f"  {s:30s}  qty={p.qty:+d}  avg={p.avg_price:.2f}  ltp={p.ltp:.2f}  pnl=Rs.{p.pnl:,.0f}")

print(f"\nCapital after: Rs.{pc._cash:,.2f}")
print(f"Realized after: Rs.{pc._realized_pnl:,.2f}")

# margins
m = pc.get_margins()
print(f"Available: Rs.{m['available']:,.2f}")
print(f"Used:      Rs.{m['used']:,.2f}")
print(f"Unrealized PnL: Rs.{m['unrealized_pnl']:,.2f}")
