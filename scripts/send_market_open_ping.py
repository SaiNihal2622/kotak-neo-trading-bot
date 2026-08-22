"""One-shot 9:00 AM IST market-open Telegram ping.
Invoked by the 09:00 cron. Uses the project's TelegramAlerter so the message
goes through the same code path as fills/EOD alerts.
"""
from __future__ import annotations

import sys
from pathlib import Path

# ensure project root on path so kotak_bot.* resolves
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kotak_bot.alerts.telegram import TelegramAlerter  # noqa: E402

MSG = (
    "Good morning. Market just opened. Bot is in position. Today's plan:\n"
    "- Regime detection running\n"
    "- Strategy selector: trending \u2192 directional, range \u2192 iron condor\n"
    "- Risk caps: 1% per trade, 3% daily\n"
    "- Will alert on every entry/exit. Use /status anytime."
)


def main() -> int:
    alerter = TelegramAlerter()
    if not alerter.enabled:
        print("ERROR: Telegram alerter disabled \u2014 TELEGRAM_BOT_TOKEN missing")
        return 1
    chat_id = alerter._get_chat_id()
    if not chat_id:
        print("ERROR: TELEGRAM_CHAT_ID missing \u2014 cannot send ping")
        return 1
    print(f"Sending 9:00 AM ping to chat_id={chat_id[:4]}\u2026{chat_id[-3:]}")
    ok = alerter.send(MSG)
    print("Result:", "OK" if ok else "FAILED")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
