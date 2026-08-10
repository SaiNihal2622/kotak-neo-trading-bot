"""Quick import test for all modules."""
import sys
from pathlib import Path

LOG = open("import_test.txt", "w", encoding="utf-8")
def o(m): LOG.write(m + "\n"); LOG.flush()

sys.path.insert(0, '.')

o("=== Import test ===")
try:
    from kotak_bot.broker import PaperClient, NeoClient, Order, OrderSide, OrderType, ProductType, OrderStatus, Position, Tick
    o("broker OK")
except Exception as e:
    o(f"broker FAIL: {e}")
try:
    from kotak_bot.broker.base import BrokerClient
    o("broker.base OK")
except Exception as e:
    o(f"broker.base FAIL: {e}")
try:
    from kotak_bot.data.live_feed import LiveFeed
    o("data.live_feed OK")
except Exception as e:
    o(f"data.live_feed FAIL: {e}")
try:
    from kotak_bot.data.historical import HistoricalData
    o("data.historical OK")
except Exception as e:
    o(f"data.historical FAIL: {e}")
try:
    from kotak_bot.signals.technical import TechnicalAnalyzer, TechnicalSignal
    o("signals.technical OK")
except Exception as e:
    o(f"signals.technical FAIL: {e}")
try:
    from kotak_bot.signals.regime import RegimeDetector, Regime, RegimeState
    o("signals.regime OK")
except Exception as e:
    o(f"signals.regime FAIL: {e}")
try:
    from kotak_bot.strategy.base import BaseStrategy, SignalContext, TradePlan, StrategyName
    from kotak_bot.strategy.directional import DirectionalDebitStrategy
    from kotak_bot.strategy.premium_selling import IronCondorStrategy, ShortStrangleStrategy
    from kotak_bot.strategy.event_play import EventStraddleStrategy
    from kotak_bot.strategy.selector import StrategySelector
    o("strategy OK")
except Exception as e:
    o(f"strategy FAIL: {e}")
try:
    from kotak_bot.risk.engine import RiskEngine, RiskState, RiskDecision
    o("risk.engine OK")
except Exception as e:
    o(f"risk.engine FAIL: {e}")
try:
    from kotak_bot.execution.order_manager import OrderManager, ManagedTrade
    o("execution.order_manager OK")
except Exception as e:
    o(f"execution.order_manager FAIL: {e}")
try:
    from kotak_bot.alerts.telegram import TelegramAlerter
    from kotak_bot.alerts.email import EmailAlerter
    o("alerts OK")
except Exception as e:
    o(f"alerts FAIL: {e}")
try:
    from kotak_bot.utils.clock import now_ist, is_market_open, market_session
    from kotak_bot.utils.logger import setup_logger
    o("utils OK")
except Exception as e:
    o(f"utils FAIL: {e}")
try:
    from backtest.engine import BacktestEngine
    o("backtest.engine OK")
except Exception as e:
    o(f"backtest.engine FAIL: {e}")
try:
    from signals.news import NewsIngestor, NewsPipeline, NewsItem
    o("signals.news OK")
except Exception as e:
    o(f"signals.news FAIL: {e}")
o("=== Import test done ===")
LOG.close()
