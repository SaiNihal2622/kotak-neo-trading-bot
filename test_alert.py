"""Send a test alert to verify the new plain-text format works."""
from dotenv import load_dotenv
load_dotenv("config/credentials.env")

from kotak_bot.alerts.telegram import TelegramAlerter

alerter = TelegramAlerter()
print(f"Enabled: {alerter.enabled}")
print(f"chat_id from env: {alerter._get_chat_id()}")

# Test all 3 methods
alerter.info("Test info message - bot is alive")
print("Info sent")
alerter.warn("Test warning")
print("Warn sent")
alerter.critical("Test critical")
print("Critical sent")

# Test the trade methods with a mock plan
from dataclasses import dataclass

@dataclass
class MockPlan:
    strategy: object
    underlying: str
    legs: list
    target: float
    stop: float
    reason: str
    def __init__(self):
        class S:
            value = "directional_debit"
        self.strategy = S()
        self.underlying = "NIFTY"
        self.legs = [{"side": "BUY", "strike": 24500, "opt_type": "CE"}]
        self.target = 112.0
        self.stop = 28.0
        self.reason = "trending regime, ADX 30"

plan = MockPlan()
alerter.trade_opened(plan)
print("trade_opened sent")
alerter.trade_closed(1500.0, "target hit")
print("trade_closed sent")
alerter.daily_report({"daily_pnl": 2500, "trades_today": 3, "wins": 2, "losses": 1, "open_positions": 0})
print("daily_report sent")
