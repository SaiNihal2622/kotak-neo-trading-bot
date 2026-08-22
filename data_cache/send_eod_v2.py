"""Send the EOD report via Telegram bot."""
import json
import csv
import sys
import urllib.request
import urllib.parse
from collections import Counter

# Force UTF-8 for stdout so emoji don't crash the console print
sys.stdout.reconfigure(encoding="utf-8")

TODAY = "2026-08-13"
TODAY_PRETTY = "13-Aug-2026 (Thu)"

# --- Load data ---
with open(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\trades_state.json") as f:
    state = json.load(f)

with open(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\paper_state.json") as f:
    paper = json.load(f)

trades_today = [t for t in state["trades"].values() if t.get("opened_at", "").startswith(TODAY)]
n_trades = len(trades_today)
total_pnl = sum(t.get("realized_pnl", 0.0) for t in trades_today)
n_wins = sum(1 for t in trades_today if t.get("realized_pnl", 0.0) > 0)
n_losses = sum(1 for t in trades_today if t.get("realized_pnl", 0.0) < 0)
n_flat = n_trades - n_wins - n_losses

pnls = [(t["plan"]["underlying"] + " " + t["plan"]["strategy"], t.get("realized_pnl", 0.0)) for t in trades_today]
best = max(pnls, key=lambda x: x[1]) if pnls else ("-", 0.0)
worst = min(pnls, key=lambda x: x[1]) if pnls else ("-", 0.0)

sig_total = 0
sig_regimes = Counter()
sig_actions = Counter()
with open(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\logs\signals.csv") as f:
    for row in csv.DictReader(f):
        if row["timestamp"].startswith(TODAY):
            sig_total += 1
            sig_regimes[row.get("regime", "")] += 1
            sig_actions[row.get("action", "")] += 1

exit_reasons = Counter(t.get("exit_reason", "open") for t in trades_today)

# Build the message (plain text, no HTML parse_mode complications)
msg_lines = [
    "\U0001F4CA EOD Report",
    f"Date: {TODAY_PRETTY}",
    "",
    f"Trades: {n_trades}",
    f"Wins: {n_wins} | Losses: {n_losses} | Flat: {n_flat}",
    f"Net P&L: Rs.{total_pnl:+,.2f}",
]

if n_trades > 0:
    msg_lines.append(f"Best trade: {best[0]} Rs.{best[1]:+,.2f}")
    msg_lines.append(f"Worst trade: {worst[0]} Rs.{worst[1]:+,.2f}")
else:
    msg_lines.append("Best trade: -")
    msg_lines.append("Worst trade: -")

msg_lines += [
    "",
    f"Signals: {sig_total} (regime: {dict(sig_regimes)})",
    f"Paper: Cash Rs.{paper['cash']:,.2f} | Cum P&L Rs.{paper['realized_pnl']:+,.2f}",
]

if exit_reasons.get("eod_square_off", 0) and all(t.get("closed_at", "").startswith(TODAY + "T09:45") for t in trades_today):
    msg_lines += [
        "",
        "\u26A0\uFE0F Both trades force-closed at 09:45 (exit_reason='eod_square_off', 0 P&L). "
        "Square-off is firing ~6h early — clock or eod config bug. Worth checking.",
    ]

if sig_regimes:
    dominant = sig_regimes.most_common(1)[0][0]
    if dominant == "range":
        outlook = "range-bound; continue with iron condors if IV rank stays supportive"
    elif dominant == "trending":
        outlook = "trending; prefer directional debit spreads"
    elif dominant == "volatile":
        outlook = "elevated vol; widen strikes, reduce size"
    else:
        outlook = "continue with current strategy"
else:
    outlook = "continue with current strategy"

msg_lines += [
    "",
    f"Tomorrow: {outlook}",
]

text = "\n".join(msg_lines)

# --- Send to Telegram ---
with open(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\config\credentials.env") as f:
    env_lines = f.readlines()

token = None
chat_id = None
for ln in env_lines:
    ln = ln.strip()
    if ln.startswith("TELEGRAM_BOT_TOKEN="):
        token = ln.split("=", 1)[1]
    elif ln.startswith("TELEGRAM_CHAT_ID="):
        chat_id = ln.split("=", 1)[1]

url = f"https://api.telegram.org/bot{token}/sendMessage"
payload = {
    "chat_id": chat_id,
    "text": text,
    "disable_web_page_preview": True,
}
data = urllib.parse.urlencode(payload).encode("utf-8")
req = urllib.request.Request(url, data=data, method="POST")
with urllib.request.urlopen(req, timeout=30) as resp:
    body = resp.read().decode("utf-8")

print("--- Message sent ---")
print(text.encode("utf-8", "replace").decode("utf-8"))
print()
print("--- Telegram response ---")
print(body)
