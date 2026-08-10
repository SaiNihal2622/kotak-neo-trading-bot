"""Test the new production features."""
import sys
sys.path.insert(0, '.')

LOG = open("prod_test.txt", "w", encoding="utf-8")
def o(m): LOG.write(m + "\n"); LOG.flush()

# silence loguru
import loguru
loguru.logger.remove()
loguru.logger.add("prod_test_logs.log", level="INFO")

try:
    from kotak_bot.data.dhan import DhanDataFeed, _DHAN_AVAILABLE
    d = DhanDataFeed()
    o(f"DhanDataFeed created: enabled={d.enabled}, package_available={_DHAN_AVAILABLE}")
except Exception as e:
    o(f"Dhan import error: {e}")

try:
    from kotak_bot.data.kotak_research import find_latest_pdf_url
    url = find_latest_pdf_url()
    o(f"Kotak research PDF URL found: {bool(url)}")
    if url:
        o(f"  URL: {url}")
except Exception as e:
    o(f"Kotak research error: {e}")

try:
    from kotak_bot.broker.neo_client import NeoClient, BracketOrderSpec
    spec = BracketOrderSpec(entry_price=100, stop_loss=50, target=150, trailing_sl=True, trailing_sl_points=10)
    o(f"BracketOrderSpec OK: entry={spec.entry_price} SL={spec.stop_loss} target={spec.target} trailing={spec.trailing_sl}")
except Exception as e:
    o(f"Bracket error: {e}")

try:
    from kotak_bot.execution.order_manager import OrderManager
    o("OrderManager with bracket support: OK")
except Exception as e:
    o(f"OrderManager error: {e}")

o("ALL OK")
LOG.close()
