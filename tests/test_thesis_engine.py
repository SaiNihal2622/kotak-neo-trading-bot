"""Tests for thesis engine, monitor, brief."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))


# ---------- thesis_engine ----------

def test_synthesize_thesis_range_regime():
    from scripts.thesis_engine import synthesize_thesis
    parts = {
        "oi": {
            "spot": 24200, "resistance": 24400, "support": 24000,
            "max_pain": 24250, "pcr": 1.05, "gex_total": 1_000_000,
        },
        "xmkt": {"india_vix": 12.0, "nifty_spot": 24200},
        "macro": {"next_event": None, "window_min": None},
        "research": {"bias": None},
        "news": {"score": 0.0, "n_items": 0},
        "paper": {"cash": 100000, "realized": 0, "open_count": 0, "open": []},
    }
    t = synthesize_thesis(parts)
    assert t["regime"] in ("pin", "range")  # positive gex + tight range
    assert t["bias"] in ("bullish", "bearish", "neutral", "cautious")
    assert 0.0 <= t["confidence"] <= 1.0
    assert 0 <= t["risk_budget_pct"] <= 100
    assert isinstance(t["preferred_strategies"], list)
    assert "narrative" in t


def test_synthesize_thesis_macro_event_caps_confidence():
    from scripts.thesis_engine import synthesize_thesis
    parts = {
        "oi": {"spot": 24200, "max_pain": 24200, "pcr": 1.2, "gex_total": 0},
        "xmkt": {"india_vix": 13.0, "nifty_spot": 24200},
        "macro": {"next_event": {"name": "RBI"}, "window_min": 30},
        "research": {"bias": "bullish"},
        "news": {"score": 0.5, "n_items": 3},
        "paper": {"cash": 100000, "realized": 0, "open_count": 0, "open": []},
    }
    t = synthesize_thesis(parts)
    assert t["triggers"]["force_square"] is True
    assert t["triggers"]["no_new_trades"] is True
    assert t["confidence"] <= 0.55  # capped by imminent event
    assert "iron_condor" in t["avoid_strategies"] or "short_strangle" in t["avoid_strategies"]


def test_synthesize_thesis_breakout_prone():
    from scripts.thesis_engine import synthesize_thesis
    parts = {
        "oi": {"spot": 24200, "gex_total": -100_000_000},
        "xmkt": {"india_vix": 22.0, "nifty_spot": 24200},
        "macro": {},
        "research": {},
        "news": {"score": 0.0, "n_items": 0},
        "paper": {},
    }
    t = synthesize_thesis(parts)
    assert t["regime"] in ("breakout_prone", "volatile")
    assert t["risk_budget_pct"] <= 45  # don't go all-in


def test_synthesize_thesis_expected_range_uses_vix():
    from scripts.thesis_engine import synthesize_thesis
    parts = {
        "oi": {"spot": 24000},
        "xmkt": {"india_vix": 16.0, "nifty_spot": 24000},
        "macro": {},
        "research": {},
        "news": {"score": 0.0, "n_items": 0},
        "paper": {},
    }
    t = synthesize_thesis(parts)
    assert t["expected_move_pts"] is not None
    assert t["expected_range"] is not None
    assert t["expected_range"][0] < 24000 < t["expected_range"][1]
    assert t["expected_range"][1] - t["expected_range"][0] == pytest.approx(2 * t["expected_move_pts"], abs=1.0)


def test_collect_cross_market_handles_no_yfinance():
    """If yfinance fails, we still get a structured dict (not exception)."""
    from scripts.thesis_engine import collect_cross_market
    with patch.dict(sys.modules, {"yfinance": None}):
        out = collect_cross_market()
    assert "ts" in out
    assert "india_vix" in out
    # values may be None but keys must exist
    for k in ("gift_nifty", "dow_fut", "crude_oil", "usdinr", "india_vix"):
        assert k in out


def test_collect_paper_state_missing_file():
    from scripts.thesis_engine import collect_paper_state
    with patch("scripts.thesis_engine.PAPER_STATE_PATH", Path("/nonexistent/paper_state.json")):
        out = collect_paper_state()
    assert out["cash"] is None
    assert out["open_count"] == 0


# ---------- thesis_monitor ----------

def test_thesis_monitor_no_thesis_is_noop(tmp_path, capsys):
    """If no thesis file exists, monitor should not write to brain_actions."""
    from scripts import thesis_monitor as tm
    with patch.object(tm, "THESIS_LATEST", tmp_path / "nothere.json"), \
         patch.object(tm, "BRAIN_ACTIONS", tmp_path / "ba.json"):
        out = tm.monitor()
    assert out["status"] == "no_thesis"
    assert not (tmp_path / "ba.json").exists()


def test_thesis_monitor_force_square_writes_close(tmp_path):
    from scripts import thesis_monitor as tm
    # thesis_engine writes IST local ts via now_ist() — match that in tests
    thesis = {
        "ts": datetime.now().isoformat(),
        "bias": "neutral", "confidence": 0.5,
        "triggers": {"force_square": True, "no_new_trades": False},
    }
    (tmp_path / "th").mkdir()
    (tmp_path / "th" / "latest.json").write_text(json.dumps(thesis))
    (tmp_path / "paper_state.json").write_text(json.dumps({
        "positions": {"t1": {"symbol": "NIFTY", "qty": 75, "pnl": 100}}
    }))
    # pre-existing actions
    (tmp_path / "brain_actions.json").write_text(json.dumps({"max_positions": 2, "actions": []}))

    with patch.object(tm, "THESIS_LATEST", tmp_path / "th" / "latest.json"), \
         patch.object(tm, "PAPER_STATE", tmp_path / "paper_state.json"), \
         patch.object(tm, "BRAIN_ACTIONS", tmp_path / "brain_actions.json"), \
         patch.object(tm, "PROPOSAL_LOG", tmp_path / "prop.jsonl"), \
         patch.object(tm, "THESIS_HISTORY", tmp_path / "hist.jsonl"):
        out = tm.monitor()

    assert out["status"] == "ok"
    assert any("force_square" in p for p in out["proposals"])
    written = json.loads((tmp_path / "brain_actions.json").read_text())
    assert written["max_positions"] == 0
    assert any(a["action"] == "CLOSE" for a in written["actions"])


def test_thesis_monitor_bias_flip_caps_to_one(tmp_path):
    from scripts import thesis_monitor as tm
    # Need at least 2 history lines so lines[-2] is the "prev" thesis
    (tmp_path / "hist.jsonl").write_text(
        json.dumps({"ts": "2026-01-01T00:00:00", "bias": "neutral", "conf": 0.5}) + "\n" +
        json.dumps({"ts": "2026-01-02T00:00:00", "bias": "bullish", "conf": 0.7}) + "\n"
    )
    # Current thesis = bearish (flip from bullish)
    thesis = {
        "ts": datetime.now().isoformat(),
        "bias": "bearish", "confidence": 0.6,
        "triggers": {"force_square": False, "no_new_trades": False},
    }
    (tmp_path / "th").mkdir()
    (tmp_path / "th" / "latest.json").write_text(json.dumps(thesis))
    (tmp_path / "paper_state.json").write_text(json.dumps({
        "positions": {"t1": {"symbol": "NIFTY", "qty": 75, "pnl": 200}}
    }))
    (tmp_path / "brain_actions.json").write_text(json.dumps({"max_positions": 2, "actions": []}))

    with patch.object(tm, "THESIS_LATEST", tmp_path / "th" / "latest.json"), \
         patch.object(tm, "PAPER_STATE", tmp_path / "paper_state.json"), \
         patch.object(tm, "BRAIN_ACTIONS", tmp_path / "brain_actions.json"), \
         patch.object(tm, "PROPOSAL_LOG", tmp_path / "prop.jsonl"), \
         patch.object(tm, "THESIS_HISTORY", tmp_path / "hist.jsonl"):
        out = tm.monitor()

    assert any("bias flip" in p for p in out["proposals"])
    written = json.loads((tmp_path / "brain_actions.json").read_text())
    assert written["max_positions"] == 1


def test_thesis_monitor_low_confidence_passes_through_when_no_positions(tmp_path):
    from scripts import thesis_monitor as tm
    thesis = {
        "ts": datetime.now().isoformat(),
        "bias": "neutral", "confidence": 0.2,
        "triggers": {"force_square": False, "no_new_trades": False},
    }
    (tmp_path / "th").mkdir()
    (tmp_path / "th" / "latest.json").write_text(json.dumps(thesis))
    (tmp_path / "paper_state.json").write_text(json.dumps({"positions": {}}))
    (tmp_path / "brain_actions.json").write_text(json.dumps({"max_positions": 2, "actions": []}))

    with patch.object(tm, "THESIS_LATEST", tmp_path / "th" / "latest.json"), \
         patch.object(tm, "PAPER_STATE", tmp_path / "paper_state.json"), \
         patch.object(tm, "BRAIN_ACTIONS", tmp_path / "brain_actions.json"), \
         patch.object(tm, "PROPOSAL_LOG", tmp_path / "prop.jsonl"), \
         patch.object(tm, "THESIS_HISTORY", tmp_path / "hist.jsonl"):
        out = tm.monitor()

    # No positions, so no need to cap
    assert out["proposals"] == []


# ---------- thesis_brief ----------

def test_thesis_brief_renders_with_full_data(tmp_path):
    from scripts import thesis_brief
    thesis = {
        "ist_time": "2026-08-25 08:30",
        "regime": "range",
        "bias": "neutral",
        "confidence": 0.55,
        "risk_budget_pct": 45,
        "max_positions": 2,
        "expected_move_pts": 170.0,
        "expected_range": [24030, 24370],
        "preferred_strategies": ["iron_condor"],
        "avoid_strategies": ["naked_short"],
        "narrative": "RANGE regime, neutral.",
        "data": {
            "oi": {"available": True, "support": 24000, "resistance": 24400,
                   "max_pain": 24250, "pcr": 1.05},
            "macro": {"next_event": None, "window_min": None},
            "xmkt": {"india_vix": 11.0, "crude_oil": 83.0, "usdinr": 95.5, "dow_fut": 53600},
            "news": {"score": 0.0, "n_items": 0, "headlines": []},
        },
        "triggers": {"force_square": False, "no_new_trades": False},
    }
    (tmp_path / "th").mkdir()
    (tmp_path / "th" / "latest.json").write_text(json.dumps(thesis))

    with patch.object(thesis_brief, "THESIS_LATEST", tmp_path / "th" / "latest.json"):
        msg = thesis_brief.build_brief()

    assert msg is not None
    assert "PRE-MARKET THESIS BRIEF" in msg
    assert "RANGE" in msg
    assert "iron_condor" in msg
    assert "VIX" in msg


def test_thesis_brief_returns_none_when_no_thesis(tmp_path):
    from scripts import thesis_brief
    with patch.object(thesis_brief, "THESIS_LATEST", tmp_path / "nope.json"):
        msg = thesis_brief.build_brief()
    assert msg is None
