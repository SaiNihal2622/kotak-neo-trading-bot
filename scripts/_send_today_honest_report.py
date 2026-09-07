"""Send the honest today-report to Telegram via telegram_alerter."""
import json
import sys
from pathlib import Path

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
sys.path.insert(0, str(ROOT / "scripts"))

# Load env
cred = ROOT / "config" / "credentials.env"
for line in cred.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        if k.strip() not in __import__("os").environ:
            __import__("os").environ[k.strip()] = v.strip().strip('"').strip("'")

ps = json.loads((ROOT / "data_cache" / "paper_state.json").read_text(encoding="utf-8"))
j = json.loads((ROOT / "data_cache" / "performance" / "daily.json").read_text(encoding="utf-8"))
n_orders_today = sum(
    1 for oid, o in ps["orders"].items()
    if (o.get("placed_at") or "").startswith("2026-09-07")
)

# Today's trade pairs
todays_fills = []
for oid, o in ps["orders"].items():
    if not (o.get("placed_at") or "").startswith("2026-09-07"):
        continue
    if o.get("status") != "complete":
        continue
    todays_fills.append({
        "sym": o["symbol"],
        "side": o["side"],
        "qty": o["filled_qty"],
        "px": o["avg_fill_price"],
        "tag": o.get("tag", ""),
    })

msg = (
    "[Mavis 22:50] Today (2026-09-07) — HONEST P&L REPORT\n\n"
    f"CASH: Rs.{ps['cash']:,.2f}\n"
    f"REALIZED P&L: Rs.{ps['realized_pnl']:+,.2f}\n"
    f"OPEN POSITIONS: {len(ps.get('positions', {}))}\n"
    f"TODAY'S ORDERS: {n_orders_today} ({len(todays_fills)} filled)\n\n"
    "WARNING: THE +Rs.16,883.70 IS PARTIALLY FAKE.\n\n"
    "Bug: orphan-auto-close at __main__.py:2065 constructed Order without\n"
    "strike/option_type/underlying, so paper_client._force_fill_market_like\n"
    "fell through to the Rs.1.00 last-resort path. 3 of 8 fills today closed\n"
    "for Rs.1.00 instead of the real ~Rs.245 / ~Rs.307 / ~Rs.548.\n\n"
    "Per-leg P&L (FIFO-matched from paper_state.json):\n"
    "  BNF 57200 PE  (long,  fake close @1.00):   -Rs.11,746.50  LOSS\n"
    "  BNF 56800 PE  (short, fake close @1.00):   +Rs.7,339.20   WIN (FAKE)\n"
    "  NIFTY 24100 PE (short, fake close @1.00):  +Rs.22,993.50  WIN (FAKE)\n"
    "  NIFTY 24300 PE (long,  real close @525.89): -Rs.1,702.50   LOSS\n"
    "  ─────────────────────────────────────────\n"
    "  Total trades: +Rs.16,883.70 (4 trade-pairs)\n"
    f"  + carryover from prior day: -Rs.264.00\n"
    f"  = bot's running realized: +Rs.{ps['realized_pnl']:,.2f}\n\n"
    "FAKE COMPONENT: ~Rs.30,332 from 2 short-closes at Rs.1.00.\n"
    "REAL P&L (without fake Rs.1.00): the BNF bear-put lost ~Rs.4-12K\n"
    "(spread decayed), NIFTY bear-put was near-zero to slightly negative.\n\n"
    "FIXES SHIPPED (3 commits today):\n"
    "  ab78e22: orphan-auto-close uses real option chain price\n"
    "  d60db8d: trade_journal.jsonl EOD reconstruction\n"
    "  6e7d977: inline trade_journal via PaperClient.on_fill callback\n"
    "  b8b8817: docs + journal entries for today\n\n"
    "BOT STATUS: NSSM RUNNING, PID 3388, new code deployed\n"
    f"TESTS: 382 pass (was 369; +13 from this session)\n"
    "LINTER: PASS\n\n"
    "LESSON: any future paper fill at exactly Rs.1.00 is a red flag.\n"
    "The inline on_fill callback now records every fill with avg_fill_price\n"
    "and expected_fill_price so future P&L is end-to-end auditable."
)

print(msg)
print("---")

# Send via telegram_alerter
from telegram_alerter import get_alerter
a = get_alerter()
if a and a.enabled:
    if a.send(msg):
        print("Sent to Telegram")
    else:
        print("Telegram send failed")
else:
    print("Telegram alerter not enabled — message NOT sent")
