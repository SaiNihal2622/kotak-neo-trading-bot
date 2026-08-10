"""Send comprehensive status to Telegram."""
import os, sys, json
sys.path.insert(0, r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot")
os.chdir(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot")
from kotak_bot.alerts.telegram import TelegramAlerter
from kotak_bot.intel.performance import PerformanceTracker
from datetime import datetime

# Read state
ps_path = "data_cache/paper_state.json"
state = {}
if os.path.exists(ps_path):
    with open(ps_path) as f:
        state = json.load(f)
positions = state.get("positions", {})
cash = state.get("cash", 0)
realized = state.get("realized_pnl", 0)
upnl = sum(p.get("pnl", 0) for p in positions.values()) if isinstance(positions, dict) else 0

# Performance
pt = PerformanceTracker()
metrics = pt.all_strategies_metrics()
metrics_text = ""
if metrics:
    lines = [f"  {m['strategy']:20s} cnt={m['count']:3d} win={m['win_rate']:.0%} avg=Rs.{m['avg_pnl']:7.0f} Sharpe={m['sharpe']:+.2f}" for m in metrics if m["count"] > 0]
    metrics_text = "\n".join(lines) if lines else "  (no closed trades yet)"

# Pos breakdown
pos_text = ""
if isinstance(positions, dict) and positions:
    for sym, p in positions.items():
        pos_text += f"  {sym} qty={p.get('qty', 0):+d} pnl=Rs.{p.get('pnl', 0):,.0f}\n"

msg = (
    f"🏛️ PRODUCTION v3.4 — Intel Layer Live\n"
    f"Time: {datetime.now().strftime('%H:%M')} IST\n"
    f"{'=' * 40}\n"
    f"💰 Capital: Rs.{cash:,.0f}\n"
    f"📈 Realized: Rs.{realized:,.0f}\n"
    f"📊 Unrealized: Rs.{upnl:,.0f}\n"
    f"📋 Open positions: {len(positions)}\n"
    f"{pos_text}\n"
    f"🎛️ NEW FEATURES LIVE:\n"
    f"✅ OI Analytics (resistance/support/max-pain/PCR/GEX) — /oi NIFTY\n"
    f"✅ Performance Attribution (per-strategy Sharpe, win rate)\n"
    f"✅ Alpha Decay Detector (auto-pause if Sharpe <-0.1 for 5 trades)\n"
    f"✅ Auto-Params Tuner (adjusts target_rr, wing_width by Sharpe)\n"
    f"✅ Position Reconciliation (every 5 min, alert on mismatch)\n"
    f"✅ Trade Journal + auto-screenshots at every entry/exit\n"
    f"✅ Compliance PDF (SEBI audit pack at EOD)\n"
    f"✅ Multi-Broker Router (Kotak + Dhan + Upstox stub, ready when creds added)\n"
    f"✅ Anomaly Detection (P&L swing >Rs.500, price spike >0.5%, volume spike 3x)\n"
    f"✅ Cross-Broker Arbitrage Detector\n"
    f"✅ Mavis Co-Pilot (cron every 10 min during market hours, sends AI advice to Telegram)\n"
    f"\n📈 Performance:\n{metrics_text}\n"
    f"\n🎯 Commands: /status /positions /pnl /regime /oi NIFTY /perf /force NIFTY /close /pause"
)

a = TelegramAlerter()
ok = a.send(msg)
print(f"text sent: {ok}")
try:
    chart = a.generate_daily_chart()
    if chart:
        ok2 = a.send_photo(chart, caption=f"Daily P&L chart @ {datetime.now().strftime('%H:%M')}")
        print(f"chart sent: {ok2}")
except Exception as e:
    print(f"chart: {e}")
