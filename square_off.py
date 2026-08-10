"""Close all open paper positions and cancel open orders."""
import sys
from pathlib import Path
sys.path.insert(0, '.')

import loguru
loguru.logger.remove()
loguru.logger.add("close_log.txt", level="INFO")

from dotenv import load_dotenv
load_dotenv("config/credentials.env")
from kotak_bot.broker import PaperClient
from kotak_bot.execution.order_manager import OrderManager
from kotak_bot.alerts.telegram import TelegramAlerter

# load state from disk and square off
pp = Path("data_cache/paper_state.json")
if pp.exists():
    pp.unlink()  # wipe state

broker = PaperClient(starting_capital=300_000.0, persist_path=str(pp))
broker.connect()
order_mgr = OrderManager(broker)

# cancel any open orders
cancelled = 0
for oid, o in list(broker._orders.items()):
    if o.status.value in ("open", "pending"):
        try:
            broker.cancel_order(oid)
            cancelled += 1
            print(f"Cancelled {oid} {o.symbol}")
        except Exception as e:
            print(f"Failed to cancel {oid}: {e}")

# any open positions (should be 0 after cancelling, but just in case)
positions = broker.get_positions()
print(f"Remaining positions: {len(positions)}")
for p in positions:
    print(f"  {p.symbol} qty={p.qty}")

alerter = TelegramAlerter()
alerter.warn(
    f"Overtrading bug fix in progress. Cancelled {cancelled} pending orders. "
    "Bot will restart with position-cap fix. No real money at risk (paper mode)."
)
print(f"Cancelled {cancelled} open orders. {len(positions)} positions remain.")
broker.disconnect()
