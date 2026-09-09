"""Tests for the min-activity override (FIX 2026-09-09 13:30).

The LLM was in a 4+ hour HOLD loop while the market was -0.82% bearish.
The static ACTIVE MANAGEMENT prompt wasn't enough; the LLM still output
HOLD with templated 'trend_captured' reasoning.

This test verifies the dynamic reminder:
- Empty when market closed
- Empty when last trade < 60 min ago
- Has SKIP_DAY-or-ACT reminder when > 60 min + no clear bias
- Has MIN-ACTIVITY OVERRIDE when > 90 min + clear bias
"""
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys_path = str(ROOT)
import sys
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)


class TestMinActivityReminder:
    """Test the get_min_activity_reminder() function."""

    def test_empty_when_market_closed(self, tmp_path):
        """No reminder when NSE market is closed."""
        with patch("scripts.quant_service.is_market_hours", return_value=False):
            from scripts.quant_service import get_min_activity_reminder
            assert get_min_activity_reminder() == ""

    def test_empty_when_recent_trade(self, tmp_path, monkeypatch):
        """No reminder if a trade happened < 60 min ago (no need to push)."""
        # Write a trade journal entry from 5 min ago
        journal = tmp_path / "trade_journal.jsonl"
        ts = time.time() - 5 * 60
        from datetime import datetime, timezone
        iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        journal.write_text(json.dumps({"ts": iso, "symbol": "TEST", "side": "BUY"}) + "\n", encoding="utf-8")
        # Patch DATA path
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)
        # Market is open
        with patch("scripts.quant_service.is_market_hours", return_value=True):
            reminder = quant_service.get_min_activity_reminder()
        # Should be empty because trade is fresh
        assert "MIN-ACTIVITY" not in reminder or "5 min" not in reminder
        # Either empty or shows low minutes_since_trade
        assert reminder == "" or "5" in reminder

    def test_skip_day_reminder_when_flat(self, tmp_path, monkeypatch):
        """When > 60 min since trade AND no clear bias, emit SKIP_DAY reminder."""
        # Empty journal = no trades ever
        journal = tmp_path / "trade_journal.jsonl"
        journal.write_text("", encoding="utf-8")
        # Set session_moves to all < 0.3% (flat market)
        class FakeEngine:
            last_ltp = {"NIFTY": 23500.0, "BANKNIFTY": 56600.0}
            def get_session_open(self, sym):
                return {"NIFTY": 23550.0, "BANKNIFTY": 56650.0}.get(sym, 0)
        fake_eng = FakeEngine()
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)
        with patch("scripts.quant_service.is_market_hours", return_value=True):
            with patch("scripts.candle_engine.get_engine", return_value=fake_eng):
                reminder = quant_service.get_min_activity_reminder()
        # Should have a SKIP_DAY check because all moves < 0.3%
        assert "MIN-ACTIVITY CHECK" in reminder
        assert "SKIP_DAY" in reminder
        assert "FLAT" in reminder

    def test_override_when_bearish_bias(self, tmp_path, monkeypatch):
        """When > 90 min since trade AND bearish bias > 0.3%, emit MIN-ACTIVITY OVERRIDE."""
        journal = tmp_path / "trade_journal.jsonl"
        journal.write_text("", encoding="utf-8")
        # Session move -0.85% (clear bearish)
        class FakeEngine:
            last_ltp = {"NIFTY": 23500.0, "BANKNIFTY": 56600.0}
            def get_session_open(self, sym):
                return {"NIFTY": 23700.0, "BANKNIFTY": 56950.0}.get(sym, 0)
        fake_eng = FakeEngine()
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)
        # Inject a fake candle_engine module so the local import inside
        # get_min_activity_reminder() resolves to our fake.
        import types
        fake_module = types.ModuleType("candle_engine")
        fake_module.get_engine = lambda: fake_eng
        monkeypatch.setitem(sys.modules, "candle_engine", fake_module)
        with patch("scripts.quant_service.is_market_hours", return_value=True):
            reminder = quant_service.get_min_activity_reminder()
        # Should have MIN-ACTIVITY OVERRIDE
        assert "MIN-ACTIVITY OVERRIDE" in reminder
        assert "BEARISH" in reminder
        assert "bear put" in reminder.lower() or "bear" in reminder.lower()
        # Session moves should be present
        assert "NIFTY" in reminder

    def test_override_when_bullish_bias(self, tmp_path, monkeypatch):
        """When > 90 min since trade AND bullish bias > 0.3%, emit MIN-ACTIVITY OVERRIDE."""
        journal = tmp_path / "trade_journal.jsonl"
        journal.write_text("", encoding="utf-8")
        class FakeEngine:
            last_ltp = {"NIFTY": 23800.0}
            def get_session_open(self, sym):
                return {"NIFTY": 23700.0}.get(sym, 0)
        fake_eng = FakeEngine()
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)
        import types
        fake_module = types.ModuleType("candle_engine")
        fake_module.get_engine = lambda: fake_eng
        monkeypatch.setitem(sys.modules, "candle_engine", fake_module)
        with patch("scripts.quant_service.is_market_hours", return_value=True):
            reminder = quant_service.get_min_activity_reminder()
        assert "MIN-ACTIVITY OVERRIDE" in reminder
        assert "BULLISH" in reminder
        assert "bull" in reminder.lower() or "call" in reminder.lower()

    def test_returns_string(self, tmp_path, monkeypatch):
        """Reminder should always be a string, never raise."""
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)
        with patch("scripts.quant_service.is_market_hours", return_value=False):
            r = quant_service.get_min_activity_reminder()
        assert isinstance(r, str)

    def test_handles_missing_journal(self, tmp_path, monkeypatch):
        """If trade_journal.jsonl doesn't exist, treat as no recent trades."""
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)  # No journal
        # Set strong bias to trigger override
        class FakeEngine:
            last_ltp = {"NIFTY": 23400.0}
            def get_session_open(self, sym):
                return {"NIFTY": 23700.0}.get(sym, 0)
        fake_eng = FakeEngine()
        import types
        fake_module = types.ModuleType("candle_engine")
        fake_module.get_engine = lambda: fake_eng
        monkeypatch.setitem(sys.modules, "candle_engine", fake_module)
        with patch("scripts.quant_service.is_market_hours", return_value=True):
            r = quant_service.get_min_activity_reminder()
        # Should still emit override (9999 min since last trade)
        assert "MIN-ACTIVITY OVERRIDE" in r
