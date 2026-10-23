"""Send THESIS FLIP alert to Telegram for cron tick 10:00 IST."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot")
sys.path.insert(0, str(ROOT))

from kotak_bot.alerts.telegram import TelegramAlerter  # noqa: E402

MSG = (
    "🚨 *THESIS FLIP* — kotak-neo-bot\n"
    "time: 2026-08-31 10:00 IST (intraday)\n"
    "\n"
    "*Bias*: `neutral` ➜ `bearish`\n"
    "*Confidence*: `0.30` ➜ `1.00` (Δ +0.70)\n"
    "*Regime*: `range` (unchanged)\n"
    "*Risk budget*: `45%` ➜ `70%` (Δ +25pp)\n"
    "*Max positions*: 2 (unchanged)\n"
    "\n"
    "*Strategies*:\n"
    "  + added: `bear_put_vertical`\n"
    "  − kept:  `iron_condor`, `short_strangle`\n"
    "\n"
    "*Market snapshot diff*:\n"
    "  • nifty_spot: `24046.55` ➜ `24027.55` (−19 pts)\n"
    "  • india_vix:  `11.145` ➜ `11.220` (+0.075)\n"
    "  • news score: `0.00` ➜ `−1.00` (bearish)\n"
    "  • crude_oil:  `85.08` ➜ `85.13` (+0.05)\n"
    "  • expected_move_pts: `168.84` ➜ `169.84`\n"
    "\n"
    "*Narrative*: **RANGE** regime, bearish (conf 100%). "
    "Spot ~24027 | VIX 11.2 | news −1.00. Playbook: 70% capital, 2 max positions.\n"
    "\n"
    "_Source: scripts/thesis_engine.py intraday @ 10:00:41_"
)

alerter = TelegramAlerter()
if not alerter.enabled:
    print("ALERTER DISABLED (no TELEGRAM_BOT_TOKEN) — would have sent:", MSG)
    sys.exit(2)

ok = alerter.send(MSG, parse_mode="Markdown")
print("send_ok:", ok)
sys.exit(0 if ok else 1)
