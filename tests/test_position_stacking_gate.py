"""Tests for the position-stacking gate + OPEN cooldown in write_decision."""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _make_decision(otype="OPEN", strategy="iron_condor_nifty"):
    return {
        "type": otype,
        "underlying": "NIFTY",
        "strategy": strategy,
        "legs": [{"side": "SELL", "qty": 75, "strike": 23050, "opt_type": "CE"}],
        "rationale": "test",
    }


def test_stacking_gate_blocks_when_book_full(monkeypatch, tmp_path):
    """An OPEN must be stripped when the book already has >= max positions."""
    from scripts import quant_service as qs
    # simulate 6 open positions in the core
    core_pos = {f"SYM{i}": {"qty": 75, "avg_price": 10.0} for i in range(6)}
    monkeypatch.setenv("KOTAK_MAX_OPEN_POSITIONS", "6")

    calls = {}

    def fake_urlopen(url, timeout=3):
        calls["url"] = url
        class R:
            def read(self):
                return json.dumps({"positions": core_pos}).encode()
        return R()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(qs, "ACTIONS", tmp_path / "actions.json")
    monkeypatch.setattr(qs, "DATA", tmp_path)
    monkeypatch.setattr(qs, "ROOT", ROOT)
    monkeypatch.setattr(qs, "now_iso", lambda: "2026-10-19T12:00:00+05:30")
    monkeypatch.setattr(qs, "_last_open_action_ts", 0.0)
    # valid paper_state so the survival gate doesn't fire first
    (tmp_path / "paper_state.json").write_text(
        json.dumps({"cash": 100000, "realized_pnl": 0, "positions": {}}), encoding="utf-8")

    logs = []
    monkeypatch.setattr(qs, "log", lambda *a, **k: logs.append(a[0] if a else ""))
    qs.write_decision(_make_decision())
    # the OPEN must be suppressed (no action file written, suppression logged)
    assert not (tmp_path / "actions.json").exists()
    assert any("position-stack" in l for l in logs)


def test_stacking_gate_blocks_same_strategy(monkeypatch, tmp_path):
    """An iron_condor OPEN must be stripped if the book already holds CE+PE."""
    from scripts import quant_service as qs
    core_pos = {
        "NIFTY23050CE": {"symbol": "NIFTY23050CE", "qty": -75, "avg_price": 10.0},
        "NIFTY22900PE": {"symbol": "NIFTY22900PE", "qty": -75, "avg_price": 10.0},
    }
    monkeypatch.setenv("KOTAK_MAX_OPEN_POSITIONS", "6")

    def fake_urlopen(url, timeout=3):
        class R:
            def read(self):
                return json.dumps({"positions": core_pos}).encode()
        return R()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(qs, "ACTIONS", tmp_path / "actions.json")
    monkeypatch.setattr(qs, "DATA", tmp_path)
    monkeypatch.setattr(qs, "ROOT", ROOT)
    monkeypatch.setattr(qs, "now_iso", lambda: "2026-10-19T12:00:00+05:30")
    monkeypatch.setattr(qs, "_last_open_action_ts", 0.0)
    (tmp_path / "paper_state.json").write_text(
        json.dumps({"cash": 100000, "realized_pnl": 0, "positions": {}}), encoding="utf-8")

    logs = []
    monkeypatch.setattr(qs, "log", lambda *a, **k: logs.append(a[0] if a else ""))
    qs.write_decision(_make_decision())
    assert not (tmp_path / "actions.json").exists()
    assert any("already holding" in l for l in logs)


def test_open_cooldown_blocks_rapid_reentry(monkeypatch, tmp_path):
    """An OPEN within the cooldown window must be suppressed."""
    from scripts import quant_service as qs
    monkeypatch.setenv("KOTAK_OPEN_COOLDOWN_SEC", "600")
    monkeypatch.setenv("KOTAK_MAX_OPEN_POSITIONS", "6")

    def fake_urlopen(url, timeout=3):
        class R:
            def read(self):
                return json.dumps({"positions": {}}).encode()
        return R()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(qs, "ACTIONS", tmp_path / "actions.json")
    monkeypatch.setattr(qs, "DATA", tmp_path)
    monkeypatch.setattr(qs, "ROOT", ROOT)
    monkeypatch.setattr(qs, "now_iso", lambda: "2026-10-19T12:00:00+05:30")
    (tmp_path / "paper_state.json").write_text(
        json.dumps({"cash": 100000, "realized_pnl": 0, "positions": {}}), encoding="utf-8")
    # simulate a recent open (cooldown active)
    monkeypatch.setattr(qs, "_last_open_action_ts", __import__("time").time() - 10)

    logs = []
    monkeypatch.setattr(qs, "log", lambda *a, **k: logs.append(a[0] if a else ""))
    qs.write_decision(_make_decision())
    assert not (tmp_path / "actions.json").exists()
    assert any("cooldown" in l for l in logs)
