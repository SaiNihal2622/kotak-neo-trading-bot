"""Check ticks now flowing."""
import sys
sys.path.insert(0, '.')
from kotak_bot.broker.paper_client import PaperClient
pc = PaperClient(fill_mode='realistic')
pc.connect()
print(f"PaperClient ticks: {len(pc._ticks)}")
for sym in list(pc._ticks.keys())[:10]:
    print(f"  {sym}: ltp={pc._ticks[sym].ltp:.2f} bid={pc._ticks[sym].bid:.2f}")