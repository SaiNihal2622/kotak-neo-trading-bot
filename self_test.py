"""Self-test the bot's command handler via direct in-process invocation."""
import os
from dotenv import load_dotenv
load_dotenv("config/credentials.env")

# Simulate a user sending /status, /pnl, /help, /time, /ping, /regime
# by directly invoking the command handler

import sys
sys.path.insert(0, ".")
from kotak_bot.alerts.telegram_commands import TelegramCommandHandler
from kotak_bot.alerts.telegram import TelegramAlerter

# wire up
alerter = TelegramAlerter()
handler = TelegramCommandHandler()

# mock status
def mock_status():
    return {
        "capital": 300000, "daily_pnl": 0, "weekly_pnl": 0, "monthly_pnl": 0,
        "trades_today": 0, "open_positions": 0, "consecutive_losses": 0,
        "paused": False, "pause_reason": "",
        "regime": "trending", "adx": 30.0, "vix": 14.0, "iv_rank": 55.0,
        "regime_confidence": 0.7, "data_source": "synthetic", "broker_type": "paper",
    }
handler.get_status = mock_status

# mock a chat message
mock_msg = {
    "chat": {"id": int(os.getenv("TELEGRAM_CHAT_ID"))},
    "from": {"id": int(os.getenv("TELEGRAM_CHAT_ID")), "is_bot": False, "first_name": "Sai"},
    "text": "",
}

# Test each command
for cmd in ["/help", "/status", "/pnl", "/regime", "/time", "/ping", "/positions"]:
    mock_msg["text"] = cmd
    # call internal method by temporarily replacing _reply to capture
    captured = []
    handler._reply = lambda chat_id, text: captured.append(text)
    parts = cmd.split(maxsplit=1)
    cmd_name = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""
    handler_fn = handler._commands.get(cmd_name)
    if handler_fn:
        try:
            reply = handler_fn(arg, mock_msg)
            print(f"{cmd}:")
            for line in reply.split("\n")[:8]:
                print(f"  {line}")
        except Exception as e:
            print(f"{cmd}: ERROR {e}")
        print()
    else:
        print(f"{cmd}: no handler")
        print()
