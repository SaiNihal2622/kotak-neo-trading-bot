"""Generate EOD summary from today's trading activity."""
import json
import csv
from collections import Counter

TODAY = "2026-08-13"

# Read trades_state.json
with open(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\trades_state.json") as f:
    state = json.load(f)

trades_today = []
for tid, t in state["trades"].items():
    opened = t.get("opened_at", "")
    if opened.startswith(TODAY):
        trades_today.append(t)

# Read paper_state
with open(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\paper_state.json") as f:
    paper = json.load(f)

# Count signals
sig_count = 0
sig_regimes = Counter()
sig_actions = Counter()
with open(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\logs\signals.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row["timestamp"].startswith(TODAY):
            sig_count += 1
            sig_regimes[row.get("regime", "")] += 1
            sig_actions[row.get("action", "")] += 1

print("=== Today's Trades ===")
print(f"Total trades opened: {len(trades_today)}")
total_pnl = 0.0
for t in trades_today:
    underlying = t["plan"]["underlying"]
    strat = t["plan"]["strategy"]
    pnl = t.get("realized_pnl", 0.0)
    total_pnl += pnl
    closed = t.get("closed_at") or "STILL OPEN"
    print(f"  - {underlying} {strat} (PnL={pnl}) opened={t['opened_at']} closed={closed}")

print(f"\nRealized P&L today: Rs.{total_pnl:.2f}")

opens = [t for t in trades_today if not t.get("closed_at")]
print(f"\nOpen positions: {len(opens)}")
for t in opens:
    print(f"  - {t['plan']['underlying']} iron condor (4 legs)")

print(f"\n=== Paper Account ===")
print(f"Cash: Rs.{paper['cash']:.2f}")
print(f"Cumulative realized P&L: Rs.{paper['realized_pnl']:.2f}")

print(f"\n=== Today's Signals ===")
print(f"Total signals: {sig_count}")
print(f"By regime: {dict(sig_regimes)}")
print(f"By action: {dict(sig_actions)}")
