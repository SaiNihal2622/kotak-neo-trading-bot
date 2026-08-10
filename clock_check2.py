"""Check current market session."""
import sys
sys.path.insert(0, '.')
from kotak_bot.utils.clock import now_ist, is_market_open, market_session
n = now_ist()
print(f"Now: {n.strftime('%Y-%m-%d %H:%M:%S IST')}")
print(f"Session: {market_session(n)}")
print(f"Market open: {is_market_open(n)}")
print(f"Weekday: {n.strftime('%A')}")
