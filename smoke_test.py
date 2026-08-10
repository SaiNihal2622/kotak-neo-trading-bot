"""Smoke test for the bot."""
import sys
import time
from pathlib import Path

sys.path.insert(0, '.')

# Use file-based output to avoid Windows console encoding issues
LOG = open("smoke_log.txt", "w", encoding="utf-8")

def out(msg):
    LOG.write(msg + "\n")
    LOG.flush()

# Redirect loguru to file only BEFORE any module import triggers logging
import loguru as _lg
_lg.logger.remove()
_lg.logger.add("smoke_logs.log", level="INFO")

from kotak_bot.broker import PaperClient, Order, OrderSide, OrderType, ProductType
from kotak_bot.broker.base import Tick
from kotak_bot.data.live_feed import LiveFeed
from kotak_bot.execution.order_manager import OrderManager
from kotak_bot.risk.engine import RiskEngine
from kotak_bot.alerts.telegram import TelegramAlerter
from kotak_bot.signals.technical import TechnicalAnalyzer
from kotak_bot.signals.regime import RegimeDetector
from kotak_bot.strategy.selector import StrategySelector
from kotak_bot.strategy.base import SignalContext

R = "Rs."  # currency safe

out("=" * 60)
out("SMOKE TEST: synthetic feed + paper broker + risk + order")
out("=" * 60)

# 1) Connect paper broker
pp = Path("data_cache/test_paper.json")
if pp.exists():
    pp.unlink()
broker = PaperClient(starting_capital=300_000, persist_path=str(pp))
broker.connect()
out(f"Broker connected. Cash: {R}{broker.get_margins()['total']:,.0f}")

# 2) Start synthetic feed
feed = LiveFeed(mode="synthetic", broker=broker)
feed.start()
feed.subscribe(["NIFTY", "BANKNIFTY"])
out("Feed started. Waiting 3s for ticks...")
time.sleep(3)

# 3) Verify ticks flowing
nifty_ltp = feed.get_ltp("NIFTY")
banknifty_ltp = feed.get_ltp("BANKNIFTY")
out(f"NIFTY LTP: {R}{nifty_ltp:,.2f}")
out(f"BANKNIFTY LTP: {R}{banknifty_ltp:,.2f}")

# 4) Get option chain
atm = int(round(nifty_ltp / 50) * 50)
opt_ltp = feed.get_ltp(f"NIFTY{atm}CE")
out(f"NIFTY {atm} CE: {R}{opt_ltp}")

# 5) Place a paper market order
order = Order(
    symbol=f"NIFTY{atm}CE",
    side=OrderSide.BUY,
    qty=75,
    order_type=OrderType.MARKET,
    product=ProductType.MIS,
    underlying="NIFTY",
    strike=atm,
    option_type="CE",
)
placed = broker.place_order(order)
out(f"Placed: {placed.order_id} status={str(placed.status)} filled={placed.filled_qty} @ {R}{placed.avg_fill_price:.2f}")

# 6) Risk engine
risk = RiskEngine({"max_daily_loss_pct": 3.0, "max_loss_per_trade_pct": 1.0, "initial_capital": 300_000})
dec = risk.check_new_trade(plan_max_loss=3000)
out(f"Risk decision: allowed={dec.allowed} reason={dec.reason} qty={dec.suggested_qty}")

# 7) Positions
positions = broker.get_positions()
out(f"Open positions: {len(positions)}")
for p in positions:
    out(f"  {p.symbol}: qty={p.qty} avg={p.avg_price:.2f} ltp={p.ltp:.2f} pnl={R}{p.pnl:.2f}")

# 8) Margins
m = broker.get_margins()
out(f"Margins: total={R}{m['total']:,.0f} available={R}{m['available']:,.0f} used={R}{m['used']:,.0f}")

# 9) Telegram
tg = TelegramAlerter()
tg.info("Smoke test from CLI")
out(f"Telegram enabled: {tg.enabled}")

# 10) Strategy selector — trending regime
out("\n--- Strategy selector test (trending) ---")
regime = RegimeDetector({})
selector = StrategySelector({})
spot = nifty_ltp
step = 50
strikes = [atm + (i - 2) * step for i in range(5)]
option_ltps = {}
for k in strikes:
    for ot in ("CE", "PE"):
        ltp = feed.get_ltp(f"NIFTY{k}{ot}")
        if ltp > 0:
            option_ltps[(k, ot)] = ltp
out(f"Strikes: {strikes}")
out(f"Option LTPs collected: {len(option_ltps)}")

ctx = SignalContext(
    symbol="NIFTY", spot=spot, vix=14.0, iv_rank=55.0,
    adx=30.0, trend_strength=0.7, regime="trending",
    timestamp=None, strikes=strikes, option_ltps=option_ltps,
)
plan = selector.select(ctx, risk.status())
if plan:
    out(f"Selected plan: {plan.strategy.value}")
    out(f"  Legs: {[(l.get('strike'), l.get('opt_type'), l.get('side')) for l in plan.legs]}")
    out(f"  Target: {R}{plan.target:.2f} | Stop: {R}{plan.stop:.2f}")
    out(f"  Reason: {plan.reason}")
else:
    out("No plan selected")

# 11) Range regime test
out("\n--- Strategy selector test (range) ---")
ctx2 = SignalContext(
    symbol="NIFTY", spot=spot, vix=11.0, iv_rank=65.0,
    adx=15.0, trend_strength=0.0, regime="range",
    timestamp=None, strikes=strikes, option_ltps=option_ltps,
)
plan2 = selector.select(ctx2, risk.status())
if plan2:
    out(f"Selected plan: {plan2.strategy.value}")
    out(f"  Reason: {plan2.reason}")
    out(f"  Legs: {[(l.get('strike'), l.get('opt_type'), l.get('side')) for l in plan2.legs]}")
else:
    out("No plan selected (range)")

feed.stop()
broker.disconnect()
out("\n" + "=" * 60)
out("SMOKE TEST PASSED")
out("=" * 60)
LOG.close()
