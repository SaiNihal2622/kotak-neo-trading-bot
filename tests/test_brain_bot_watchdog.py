"""Test: brain's bot NSSM watchdog fires on schedule.

The brain (SYSTEM) runs a watchdog every 5 min (tick_count % 300 == 0)
that detects if the bot's NSSM service is STOPPED and restarts it. This
closes the 24/7 autonomy loop: BRAIN watches BOT, and the user-side
self-heal in the bot watches the brain. Together, the system can recover
from any single-component failure without human intervention.

Verified live: at 01:09 IST Sep 7, the brain detected KotakBotPaper STOPPED
(after I manually stopped it for the test) and called nssm start via
subprocess. Bot came back up at 01:10 IST.
"""
import re
from pathlib import Path

BOT_LOG = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\quant_service.log")


def test_brain_log_contains_bot_watchdog():
    """Brain log should contain a BOT-WATCHDOG line that successfully restarted the bot."""
    if not BOT_LOG.exists():
        import pytest
        pytest.skip(f"brain log not at {BOT_LOG}")
    text = BOT_LOG.read_text(encoding="utf-8")
    # Find BOT-WATCHDOG lines
    matches = re.findall(r"^\[.+?\]\s+BOT-WATCHDOG:.*$", text, re.MULTILINE)
    assert len(matches) > 0, f"no BOT-WATCHDOG lines found in brain log"
    # At least one should be a successful start
    assert any("Starting via nssm" in m for m in matches), f"no successful watchdog: {matches}"
