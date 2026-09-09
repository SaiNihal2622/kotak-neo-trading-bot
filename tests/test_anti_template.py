"""Tests for the anti-template check (FIX 2026-09-09 15:50).

The LLM was producing 60+ identical-templated HOLDs in a row with
"REGIME: Bearish trend day fully captured" rationale. The
system_enforcement_check() didn't catch this because the LLM was
making decisions every minute (not silent).

The new _anti_template_check() detects:
- 3+ consecutive HOLDs with the same first-60-chars fingerprint
- 30+ min since last OPEN/CLOSE
- During market hours

And forces one of:
- CLOSE_ALL if position in profit (>Rs.200) → take profit
- CLOSE_ALL if position in loss (<-Rs.500) → cut loss
- OPEN new position in bias direction if existing position is small P&L
- OPEN fresh position if no position AND clear bias
"""
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
import sys

import pytest

ROOT = Path(__file__).parent.parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _write_decisions(tmp_path, decisions):
    """Write a list of decisions to the quant_service_decisions.jsonl file."""
    p = tmp_path / "quant_service_decisions.jsonl"
    lines = []
    base_ts = datetime.now(timezone.utc) - timedelta(minutes=10)
    for i, d in enumerate(decisions):
        d_full = {"ts": (base_ts + timedelta(seconds=i*30)).isoformat(), "decision": d}
        lines.append(json.dumps(d_full))
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestAntiTemplateCheck:
    """Test the _anti_template_check() function."""

    def test_no_check_market_closed(self, tmp_path, monkeypatch):
        """No anti-template enforcement if market is closed."""
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)
        _write_decisions(tmp_path, [
            {"type": "HOLD", "rationale": "REGIME: bearish trend day fully captured. NIFTY -1%."} for _ in range(5)
        ])
        with patch("scripts.quant_service.is_market_hours", return_value=False):
            result = quant_service._anti_template_check({"paper": {"positions": {}}})
        assert result is None

    def test_no_check_few_decisions(self, tmp_path, monkeypatch):
        """No anti-template enforcement if there are < 3 recent decisions."""
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)
        _write_decisions(tmp_path, [
            {"type": "HOLD", "rationale": "REGIME: bearish. NIFTY -1%."}
        ])
        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._anti_template_check({"paper": {"positions": {}}})
        assert result is None

    def test_no_check_different_rationales(self, tmp_path, monkeypatch):
        """No anti-template if recent HOLDs have different rationales."""
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)
        _write_decisions(tmp_path, [
            {"type": "HOLD", "rationale": "REGIME: bearish trend day fully captured. NIFTY -1%."},
            {"type": "HOLD", "rationale": "REGIME: different rationale this time. BANKNIFTY -0.5%."},
            {"type": "HOLD", "rationale": "REGIME: yet another reason for HOLD. SENSEX -0.3%."},
            {"type": "HOLD", "rationale": "REGIME: bearish trend day fully captured. NIFTY -1%."},
        ])
        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._anti_template_check({"paper": {"positions": {}}})
        assert result is None

    def test_no_check_recent_action(self, tmp_path, monkeypatch):
        """No anti-template if there was a recent OPEN/CLOSE action."""
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)
        # 5 identical HOLDs but the most recent was an OPEN 5 min ago
        _write_decisions(tmp_path, [
            {"type": "HOLD", "rationale": "REGIME: bearish trend day fully captured. NIFTY -1%."} for _ in range(4)
        ])
        # Add a recent OPEN
        p = tmp_path / "quant_service_decisions.jsonl"
        ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": ts, "decision": {"type": "OPEN", "rationale": "test"}}) + "\n")
        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._anti_template_check({"paper": {"positions": {}}})
        assert result is None  # recent OPEN — let LLM keep going

    def test_anti_template_takes_profit(self, tmp_path, monkeypatch):
        """Anti-template forces CLOSE when position is in profit (>= Rs.200)."""
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)
        _write_decisions(tmp_path, [
            {"type": "HOLD", "rationale": "REGIME: bearish trend day fully captured. NIFTY -1%."} for _ in range(5)
        ])
        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._anti_template_check({
                "paper": {"positions": {"NIFTY_PE": {"qty": 75, "pnl": 500.0}}}
            })
        assert result is not None
        assert result["trigger"] == "template_hold_streak"
        assert result["consecutive_holds"] == 5
        assert result["actions"][0]["type"] == "CLOSE"
        assert result["actions"][0]["strategy"] == "system_enforced_take_profit"
        assert "profit" in result["actions"][0]["rationale"].lower()

    def test_anti_template_cuts_loss(self, tmp_path, monkeypatch):
        """Anti-template forces CLOSE when position is in loss (<= -Rs.500)."""
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)
        _write_decisions(tmp_path, [
            {"type": "HOLD", "rationale": "REGIME: bearish trend day fully captured. NIFTY -1%."} for _ in range(5)
        ])
        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._anti_template_check({
                "paper": {"positions": {"NIFTY_PE": {"qty": 75, "pnl": -800.0}}}
            })
        assert result is not None
        assert result["actions"][0]["type"] == "CLOSE"
        assert result["actions"][0]["strategy"] == "system_enforced_cut_loss"

    def test_anti_template_scales_up(self, tmp_path, monkeypatch):
        """Anti-template opens a NEW position in bias direction when existing P&L is small."""
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)
        _write_decisions(tmp_path, [
            {"type": "HOLD", "rationale": "REGIME: bearish trend day fully captured. NIFTY -1%."} for _ in range(5)
        ])
        class FakeEng:
            last_ltp = {"NIFTY": 23500.0}
            def get_session_open(self, sym):
                return {"NIFTY": 23700.0}.get(sym, 0)  # -0.85% bearish
        import types
        fake_module = types.ModuleType("candle_engine")
        fake_module.get_engine = lambda: FakeEng()
        monkeypatch.setitem(sys.modules, "candle_engine", fake_module)
        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._anti_template_check({
                "paper": {"positions": {"NIFTY_PE": {"qty": 75, "pnl": 50.0}}}  # small P&L
            })
        assert result is not None
        assert result["actions"][0]["type"] == "OPEN"
        # Should be a bear put vertical in NIFTY (bearish bias)
        action = result["actions"][0]
        assert action["underlying"] == "NIFTY"
        assert "scale" in action["strategy"].lower()
        assert action["strategy"] == "system_enforced_scale_bear"

    def test_anti_template_opens_fresh_when_no_position(self, tmp_path, monkeypatch):
        """Anti-template opens a fresh position when no position AND clear bias."""
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)
        _write_decisions(tmp_path, [
            {"type": "HOLD", "rationale": "REGIME: bearish trend day fully captured. NIFTY -1%."} for _ in range(5)
        ])
        class FakeEng:
            last_ltp = {"NIFTY": 23500.0}
            def get_session_open(self, sym):
                return {"NIFTY": 23700.0}.get(sym, 0)  # -0.85% bearish
        import types
        fake_module = types.ModuleType("candle_engine")
        fake_module.get_engine = lambda: FakeEng()
        monkeypatch.setitem(sys.modules, "candle_engine", fake_module)
        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._anti_template_check({
                "paper": {"positions": {}}  # no positions
            })
        assert result is not None
        assert result["actions"][0]["type"] == "OPEN"
        action = result["actions"][0]
        assert action["underlying"] == "NIFTY"
        assert action["strategy"] == "system_enforced_anti_template_bear"

    def test_anti_template_no_enforcement_no_signal(self, tmp_path, monkeypatch):
        """Anti-template does nothing if no position AND no clear bias."""
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)
        _write_decisions(tmp_path, [
            {"type": "HOLD", "rationale": "REGIME: bearish trend day fully captured. NIFTY -1%."} for _ in range(5)
        ])
        class FakeEng:
            last_ltp = {"NIFTY": 23500.0}
            def get_session_open(self, sym):
                return {"NIFTY": 23520.0}.get(sym, 0)  # flat
        import types
        fake_module = types.ModuleType("candle_engine")
        fake_module.get_engine = lambda: FakeEng()
        monkeypatch.setitem(sys.modules, "candle_engine", fake_module)
        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._anti_template_check({
                "paper": {"positions": {}}
            })
        assert result is None  # no position + no signal — let LLM HOLD

    def test_anti_template_does_not_match_with_actions(self, tmp_path, monkeypatch):
        """Anti-template only fires if last 5 are all HOLDs (no recent OPEN/CLOSE)."""
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)
        # 3 HOLDs with same fingerprint, then 1 OPEN, then 2 HOLDs with same fingerprint
        # The 5th-from-last is OPEN, so this should not trigger
        _write_decisions(tmp_path, [
            {"type": "HOLD", "rationale": "REGIME: bearish trend day fully captured. NIFTY -1%."},
            {"type": "HOLD", "rationale": "REGIME: bearish trend day fully captured. NIFTY -1%."},
            {"type": "HOLD", "rationale": "REGIME: bearish trend day fully captured. NIFTY -1%."},
            {"type": "OPEN", "rationale": "opening new trade"},
            {"type": "HOLD", "rationale": "REGIME: bearish trend day fully captured. NIFTY -1%."},
            {"type": "HOLD", "rationale": "REGIME: bearish trend day fully captured. NIFTY -1%."},
        ])
        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._anti_template_check({"paper": {"positions": {}}})
        # Recent OPEN is within 30 min — should not trigger
        # (the time check is on last_action_ts)
        assert result is None


class TestSystemAuditTemplateDetection:
    """Test the audit's template-streak detection."""

    def test_audit_detects_template_loop(self, tmp_path, monkeypatch):
        """The audit should report 'error' status when 3+ identical HOLDs in a row."""
        import scripts._system_audit as sa
        monkeypatch.setattr(sa, "DCACHE", tmp_path)
        monkeypatch.setattr(sa, "OUT", tmp_path / "system_audit.json")
        # Write 5 identical HOLD rationales
        _write_decisions(tmp_path, [
            {"type": "HOLD", "rationale": "REGIME: bearish trend day fully captured. NIFTY -1%."} for _ in range(5)
        ])
        # Write minimal state files
        (tmp_path / "quant_service_state.json").write_text("{}", encoding="utf-8")
        (tmp_path / "paper_state.json").write_text(
            json.dumps({"cash": 100000, "positions": {}, "realized_pnl": 0}), encoding="utf-8"
        )
        (tmp_path / "fii_dii.json").write_text(json.dumps({"rows": [], "summary": {"is_stale": True}}), encoding="utf-8")
        (tmp_path / "news_feed_meta.json").write_text(
            json.dumps({"total": 0, "sources_ok": 0, "sources_failed": 0}), encoding="utf-8"
        )
        (tmp_path / "trade_journal.jsonl").write_text("", encoding="utf-8")
        sa.main()
        report = json.loads((tmp_path / "system_audit.json").read_text(encoding="utf-8"))
        activity = report["subsystems"]["brain_activity"]
        assert activity["template_streak"] >= 3
        assert activity["status"] in ("error", "warn")
        assert "template" in activity["details"].lower() or "diversity" in activity["details"].lower()

    def test_audit_no_template_when_diverse(self, tmp_path, monkeypatch):
        """The audit should report 'ok' when decisions are diverse."""
        import scripts._system_audit as sa
        monkeypatch.setattr(sa, "DCACHE", tmp_path)
        monkeypatch.setattr(sa, "OUT", tmp_path / "system_audit.json")
        # Write DIVERSE decisions
        _write_decisions(tmp_path, [
            {"type": "HOLD", "rationale": "INDUSINDBK -0.32% is noise"},
            {"type": "HOLD", "rationale": "BANKNIFTY -0.30% is mild sector drift"},
            {"type": "OPEN", "rationale": "Bearish bias confirmed, opening vertical"},
            {"type": "HOLD", "rationale": "Watching for confirmation"},
            {"type": "HOLD", "rationale": "Session moved, waiting for entry"},
        ])
        (tmp_path / "quant_service_state.json").write_text("{}", encoding="utf-8")
        (tmp_path / "paper_state.json").write_text(
            json.dumps({"cash": 100000, "positions": {}, "realized_pnl": 0}), encoding="utf-8"
        )
        (tmp_path / "fii_dii.json").write_text(json.dumps({"rows": [], "summary": {}}), encoding="utf-8")
        (tmp_path / "news_feed_meta.json").write_text(
            json.dumps({"total": 0, "sources_ok": 0, "sources_failed": 0}), encoding="utf-8"
        )
        (tmp_path / "trade_journal.jsonl").write_text("", encoding="utf-8")
        sa.main()
        report = json.loads((tmp_path / "system_audit.json").read_text(encoding="utf-8"))
        activity = report["subsystems"]["brain_activity"]
        assert activity["diversity_score"] > 0.7
        assert activity["template_streak"] < 3
