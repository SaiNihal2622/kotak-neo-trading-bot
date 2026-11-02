"""Check what _rule_based_decision returns for the signal_confirmation test."""
import sys, os
sys.path.insert(0, r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot")
os.environ["KOTAK_ENABLE_SWING"] = "0"
from datetime import datetime
from zoneinfo import ZoneInfo
IST = ZoneInfo("Asia/Kolkata")
import system.brain.brain_daemon as bd_mod
print("ENABLE_SWING after import:", bd_mod.ENABLE_SWING)
bd_mod._is_force_square_time = lambda d: False
bd_mod._now_ist = lambda: datetime(2026, 10, 5, 11, 0, tzinfo=IST)
from system.brain.brain_daemon import BrainDaemon
bd = BrainDaemon()
print("bd.ENABLE_SWING:", getattr(bd, "ENABLE_SWING", "?"))
sig = {
    "regime": "trending_up", "vix": 13.5, "adx": 0.30,
    "rsi": 65, "session_pct": 0.30, "dist_from_vwap": 0.12,
    "open_positions": [], "realized_pnl": 0,
}
d = bd._rule_based_decision(sig)
import json
print(json.dumps(d, indent=2, default=str))
