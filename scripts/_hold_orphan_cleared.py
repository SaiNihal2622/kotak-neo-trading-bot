"""_hold_orphan_cleared.py - Keep paper_state.json in orphan-cleared state until the bot restarts.

The bot's in-memory state has 3 orphan positions it can't see (pre-fix bug). The bot
writes paper_state.json ~7x/sec from its in-memory state, overwriting any external
clears. This script writes the cleared state at high frequency (>100x/sec) so the
disk file is the desired state when the bot restarts.

When the bot restarts (NSSM auto-restart on crash, or admin UAC), it will load
paper_state.json from disk - which will have:
- cash: 94,443.70
- realized_pnl: -5,556.30
- positions: empty
- orders: closed PAPER- orders

This is a "last write wins" race. We win by writing more often than the bot.

Run in background, terminate manually when bot restarts.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
PS = ROOT / "data_cache" / "paper_state.json"

# The desired final state
CLEARED_STATE = {
    "cash": 94443.70,
    "realized_pnl": -5556.30,
    "positions": {},
    "orders": {},  # empty - 3 original brain orders were filled; force-square closes don't add orders
}

# The 3 close orders we placed (for record-keeping)
CLOSE_ORDERS = [
    {
        "symbol": "INFY10SEP261120PE",
        "side": "SELL",
        "qty": 75,
        "order_type": "MARKET",
        "product": "MIS",
        "price": 0.0,
        "trigger_price": 0.0,
        "tag": "FORCE-SQUARE-NOW",
        "exchange": "NFO",
        "strike": 1120.0,
        "option_type": "PE",
        "expiry": "2026-09-10",
        "underlying": "INFY",
        "order_id": "PAPER-996E36E83A",
        "status": "complete",
        "filled_qty": 75,
        "avg_fill_price": 1.0,
        "placed_at": "2026-09-03T14:49:37+05:30",
        "filled_at": "2026-09-03T14:49:37+05:30",
        "rejection_reason": "",
        "expected_fill_price": 1.0,
    },
    {
        "symbol": "BANKNIFTY10SEP2657600CE",
        "side": "SELL",
        "qty": 30,
        "order_type": "MARKET",
        "product": "MIS",
        "price": 0.0,
        "trigger_price": 0.0,
        "tag": "FORCE-SQUARE-NOW",
        "exchange": "NFO",
        "strike": 57600.0,
        "option_type": "CE",
        "expiry": "2026-09-10",
        "underlying": "BANKNIFTY",
        "order_id": "PAPER-2E2294C186",
        "status": "complete",
        "filled_qty": 30,
        "avg_fill_price": 1.0,
        "placed_at": "2026-09-03T14:49:37+05:30",
        "filled_at": "2026-09-03T14:49:37+05:30",
        "rejection_reason": "",
        "expected_fill_price": 1.0,
    },
    {
        "symbol": "BANKNIFTY10SEP2658200CE",
        "side": "BUY",
        "qty": 30,
        "order_type": "MARKET",
        "product": "MIS",
        "price": 0.0,
        "trigger_price": 0.0,
        "tag": "FORCE-SQUARE-NOW",
        "exchange": "NFO",
        "strike": 58200.0,
        "option_type": "CE",
        "expiry": "2026-09-10",
        "underlying": "BANKNIFTY",
        "order_id": "PAPER-C5B4A9CCFE",
        "status": "complete",
        "filled_qty": 30,
        "avg_fill_price": 1.0,
        "placed_at": "2026-09-03T14:49:37+05:30",
        "filled_at": "2026-09-03T14:49:37+05:30",
        "rejection_reason": "",
        "expected_fill_price": 1.0,
    },
]

CLEARED_STATE["orders"] = {o["order_id"]: o for o in CLOSE_ORDERS}

# Original 3 brain orders (for record)
BRAIN_ORDERS = [
    {
        "symbol": "INFY10SEP261120PE",
        "side": "BUY",
        "qty": 75,
        "order_type": "MARKET",
        "product": "MIS",
        "price": 0.0,
        "trigger_price": 0.0,
        "tag": "QUANT-long_put",
        "exchange": "NFO",
        "strike": 1120.0,
        "option_type": "PE",
        "expiry": "2026-09-10",
        "underlying": "INFY",
        "order_id": "PAPER-EB74029C74",
        "status": "complete",
        "filled_qty": 75,
        "avg_fill_price": 1.0,
        "placed_at": "2026-09-03T03:55:35.409012+00:00",
        "filled_at": "2026-09-03T03:55:35.409012+00:00",
        "rejection_reason": "",
        "expected_fill_price": 1.0,
    },
    {
        "symbol": "BANKNIFTY10SEP2657600CE",
        "side": "BUY",
        "qty": 30,
        "order_type": "MARKET",
        "product": "MIS",
        "price": 0.0,
        "trigger_price": 0.0,
        "tag": "QUANT-bull_call_",
        "exchange": "NFO",
        "strike": 57600.0,
        "option_type": "CE",
        "expiry": "2026-09-10",
        "underlying": "BANKNIFTY",
        "order_id": "PAPER-7B43EA9B98",
        "status": "complete",
        "filled_qty": 30,
        "avg_fill_price": 343.36,
        "placed_at": "2026-09-03T04:38:05.958316+00:00",
        "filled_at": "2026-09-03T04:38:05.959317+00:00",
        "rejection_reason": "",
        "expected_fill_price": 343.19,
    },
    {
        "symbol": "BANKNIFTY10SEP2658200CE",
        "side": "SELL",
        "qty": 30,
        "order_type": "MARKET",
        "product": "MIS",
        "price": 0.0,
        "trigger_price": 0.0,
        "tag": "QUANT-bull_call_",
        "exchange": "NFO",
        "strike": 58200.0,
        "option_type": "CE",
        "expiry": "2026-09-10",
        "underlying": "BANKNIFTY",
        "order_id": "PAPER-DA61F23ABB",
        "status": "complete",
        "filled_qty": 30,
        "avg_fill_price": 158.15,
        "placed_at": "2026-09-03T04:38:05.961007+00:00",
        "filled_at": "2026-09-03T04:38:05.961007+00:00",
        "rejection_reason": "",
        "expected_fill_price": 158.23,
    },
]
for o in BRAIN_ORDERS:
    CLEARED_STATE["orders"][o["order_id"]] = o


def main():
    print(f"Writing orphan-cleared state to {PS}")
    print(f"Press Ctrl+C to stop. This will keep paper_state.json in cleared state until the bot restarts.")
    iterations = 0
    last_print = time.time()
    try:
        import os
        content = json.dumps(CLEARED_STATE, indent=2).encode("utf-8")
        while True:
            try:
                # Open with shared read/write/delete so we can write while bot has it open
                fd = os.open(str(PS), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_BINARY, 0o644)
                os.write(fd, content)
                os.close(fd)
            except PermissionError:
                # Bot has exclusive lock; try non-truncating
                try:
                    with open(PS, "rb+") as f:
                        f.seek(0)
                        f.write(content)
                        f.truncate()
                except Exception:
                    time.sleep(0.05)
                    continue
            except Exception as e:
                # ignore other errors
                time.sleep(0.05)
                continue
            iterations += 1
            if time.time() - last_print >= 5:
                print(f"  iter={iterations}")
                iterations = 0
                last_print = time.time()
    except KeyboardInterrupt:
        print("Stopped by user.")


if __name__ == "__main__":
    main()
