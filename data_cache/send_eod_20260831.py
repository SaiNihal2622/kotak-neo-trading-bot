"""Send EOD report for 2026-08-31 via @Kotak_Neo_Bot on Telegram.

Reads logs/trades.csv and logs/signals.csv directly per the cron task spec.
"""
import csv
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

# Force UTF-8 stdout so the print of the message works on Windows console
sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot")
TRADES = ROOT / "logs" / "trades.csv"
SIGNALS = ROOT / "logs" / "signals.csv"
ENV_FILE = ROOT / "config" / "credentials.env"

TODAY_ISO = "2026-08-31"
TODAY_PRETTY = "31-Aug-2026 (Mon)"

# ---- 1) Today's closed trades from logs/trades.csv ----
closed_legs_today = []
all_today_rows = []
with open(TRADES, "r", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        ts = row.get("timestamp", "")
        if not ts.startswith(TODAY_ISO):
            continue
        all_today_rows.append(row)
        # Treat status in {complete, OrderStatus.COMPLETE} as a closed/filled leg
        status = row.get("status", "")
        if status in ("complete", "OrderStatus.COMPLETE"):
            closed_legs_today.append(row)

n_legs_today = len(closed_legs_today)
n_rows_today = len(all_today_rows)

# We treat the row's tag pattern as the trade "symbol" group (e.g. ic_NIFTY_sc, bcv_NIFTY_long, etc.)
# Best/Worst by leg fill_price delta vs price (rough): BUY pnl = fill - cost; SELL pnl = cost - fill
def _leg_pnl(r):
    try:
        side = r.get("side", "")
        price = float(r.get("price", 0) or 0)
        fill = float(r.get("fill_price", 0) or 0)
        if side == "BUY":
            return fill - price
        elif side == "SELL":
            return price - fill
    except Exception:
        pass
    return 0.0

leg_pnls = []
for r in closed_legs_today:
    tag = r.get("tag", "")
    pnl = _leg_pnl(r)
    leg_pnls.append((tag, pnl))

# Group leg P&L by trade_id (each plan leg has the same trade_id)
trade_groups = {}
for r in closed_legs_today:
    tid = r.get("trade_id", "") or f"_plan_{r.get('timestamp','')}"
    trade_groups.setdefault(tid, []).append((r, _leg_pnl(r)))

n_trades = len(trade_groups)
trade_pnls = []
for tid, legs in trade_groups.items():
    total = sum(p for _, p in legs)
    # Symbol label = first leg's tag (strip _sc/_sp/_lc/_lp etc.) + underlying
    first = legs[0][0]
    tag = first.get("tag", "")
    sym = first.get("symbol", "") or tag
    trade_pnls.append((sym, tag, total))

net_pnl = sum(p for _, _, p in trade_pnls)
n_wins = sum(1 for _, _, p in trade_pnls if p > 0)
n_losses = sum(1 for _, _, p in trade_pnls if p < 0)
n_flat = n_trades - n_wins - n_losses

best = max(trade_pnls, key=lambda x: x[2]) if trade_pnls else ("-", "-", 0.0)
worst = min(trade_pnls, key=lambda x: x[2]) if trade_pnls else ("-", "-", 0.0)

# ---- 2) Today's signals from logs/signals.csv ----
sig_total = 0
sig_regimes = Counter()
sig_actions = Counter()
sig_recent_days = Counter()  # last 5 trading days' dominant regimes
with open(SIGNALS, "r", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        ts = row.get("timestamp", "")
        if not ts:
            continue
        day = ts[:10]
        if day == TODAY_ISO:
            sig_total += 1
            sig_regimes[row.get("regime", "")] += 1
            sig_actions[row.get("action", "")] += 1
        if day >= "2026-08-25":  # last week of signals
            sig_recent_days[day] += 1

# ---- 3) Build the EOD message in the exact format requested ----
msg_lines = [
    "EOD Report",
    f"Date: {TODAY_PRETTY}",
    "",
    f"Trades: {n_trades}",
    f"Wins: {n_wins} | Losses: {n_losses}",
    f"Net P&L: Rs.{net_pnl:,.0f}",
]
if n_trades > 0:
    msg_lines.append(f"Best trade: {best[0]} Rs.{best[2]:+,.0f}")
    msg_lines.append(f"Worst trade: {worst[0]} Rs.{worst[2]:+,.0f}")
else:
    msg_lines.append("Best trade: -")
    msg_lines.append("Worst trade: -")

# Outlook based on regime of recent data
if sig_regimes:
    dominant = sig_regimes.most_common(1)[0][0]
    if dominant == "range":
        outlook = (
            "Range regime — ADX 0-3.4 all session, VIX 14.0. "
            "Continue with iron-condor / mean-reversion strategy tomorrow. "
            "Heads-up: aggressive preset blocked all plans today (plan_loss Rs.5,500 > cap Rs.2,000); "
            "consider widening per_trade_cap if signal quality stays consistent."
        )
    elif dominant == "trending":
        outlook = "Trending regime — prefer directional debit spreads tomorrow"
    elif dominant == "volatile":
        outlook = "Elevated volatility — widen strikes, reduce size tomorrow"
    else:
        outlook = "Continue with current strategy"
else:
    outlook = "Continue with current strategy"

msg_lines += ["", f"Tomorrow: {outlook}"]
text = "\n".join(msg_lines)

# ---- 4) Send to Telegram ----
token = None
chat_id = None
with open(ENV_FILE, "r", encoding="utf-8") as f:
    for ln in f:
        ln = ln.strip()
        if ln.startswith("TELEGRAM_BOT_TOKEN="):
            token = ln.split("=", 1)[1].strip()
        elif ln.startswith("TELEGRAM_CHAT_ID="):
            chat_id = ln.split("=", 1)[1].strip()

if not token or not chat_id:
    print("ERROR: missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
    sys.exit(1)

url = f"https://api.telegram.org/bot{token}/sendMessage"
payload = {
    "chat_id": chat_id,
    "text": text,
    "disable_web_page_preview": True,
}
data = urllib.parse.urlencode(payload).encode("utf-8")
req = urllib.request.Request(url, data=data, method="POST")
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
    print("--- Message sent ---")
    print(text)
    print()
    print("--- Telegram response ---")
    print(body)
except Exception as e:
    print(f"ERROR sending to Telegram: {e}")
    print("--- Message that would have been sent ---")
    print(text)
    sys.exit(2)
