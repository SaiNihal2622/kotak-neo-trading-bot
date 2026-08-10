"""Test all new modules import correctly."""
import sys
sys.path.insert(0, '.')

LOG = open("import_test2.txt", "w", encoding="utf-8")
def o(m): LOG.write(m + "\n"); LOG.flush()

# silence loguru
import loguru
loguru.logger.remove()
loguru.logger.add("import_test2_logs.log", level="INFO")

try:
    from kotak_bot.broker.neo_client import NeoClient, BracketOrderSpec
    o("NeoClient + BracketOrderSpec OK")
except Exception as e:
    o(f"NeoClient FAIL: {e}")

try:
    from kotak_bot.broker.paper_client import PaperClient
    o("PaperClient OK (with fixed LIMIT fill)")
except Exception as e:
    o(f"PaperClient FAIL: {e}")

try:
    from kotak_bot.data.dhan import DhanDataFeed
    o("DhanDataFeed OK")
except Exception as e:
    o(f"DhanDataFeed FAIL: {e}")

try:
    from kotak_bot.data.kotak_research import daily_research_summary
    o("Kotak research PDF crawler OK")
except Exception as e:
    o(f"Kotak research FAIL: {e}")

LOG.close()
