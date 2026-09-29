"""Tests for the brain bridge — Phase 5.

The brain bridge connects the legacy LLM brain (scripts/quant_service.py)
to the new event-sourced core by reading decision files and submitting
plans via /api/plan.

These tests verify:
1. The bridge reads quant_actions.json and submits via /api/plan
2. The bridge marks actions consumed to prevent re-submission
3. The bridge handles system_enforced_action.json (LLM-silent fallback)
4. The bridge is resilient to core being unavailable
5. Lot size and symbol formatting match the legacy bot's logic
"""
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "system"))


class TestBrainBridgePlanBuilding:
    """The bridge converts legacy actions into /api/plan legs."""

    def test_build_legs_for_iron_condor(self):
        """A 4-leg iron condor action produces 4 legs with correct symbols."""
        from bridge.brain_bridge import BrainBridge

        bridge = BrainBridge(core_url="http://testserver")
        action = {
            "strategy": "iron_condor_nifty",
            "underlying": "NIFTY",
            "legs": [
                {"side": "SELL", "strike": 23050, "opt_type": "CE",
                 "expiry": "2026-10-01", "qty": 1},
                {"side": "BUY", "strike": 23100, "opt_type": "CE",
                 "expiry": "2026-10-01", "qty": 1},
                {"side": "SELL", "strike": 22850, "opt_type": "PE",
                 "expiry": "2026-10-01", "qty": 1},
                {"side": "BUY", "strike": 22800, "opt_type": "PE",
                 "expiry": "2026-10-01", "qty": 1},
            ],
        }
        legs = bridge._build_plan_legs(action)
        assert len(legs) == 4
        # Verify symbol format: NIFTY01OCT2623050CE
        assert legs[0]["symbol"] == "NIFTY01OCT2623050CE"
        assert legs[0]["side"] == "SELL"
        assert legs[0]["qty"] == 75  # NIFTY lot size
        assert legs[0]["underlying"] == "NIFTY"
        assert legs[2]["symbol"] == "NIFTY01OCT2622850PE"
        assert legs[2]["side"] == "SELL"

    def test_build_legs_with_lot_sizes(self):
        """Lot sizes differ per underlying."""
        from bridge.brain_bridge import BrainBridge

        bridge = BrainBridge(core_url="http://testserver")
        # BANKNIFTY lot = 30
        action_bn = {
            "strategy": "iron_condor_bn",
            "underlying": "BANKNIFTY",
            "legs": [{"side": "SELL", "strike": 48000, "opt_type": "CE",
                      "expiry": "2026-10-01", "qty": 1}],
        }
        legs = bridge._build_plan_legs(action_bn)
        assert legs[0]["qty"] == 30  # BANKNIFTY lot
        # FINNIFTY lot = 65
        action_fn = {
            "strategy": "iron_condor_fn",
            "underlying": "FINNIFTY",
            "legs": [{"side": "BUY", "strike": 25000, "opt_type": "PE",
                      "expiry": "2026-10-01", "qty": 1}],
        }
        legs = bridge._build_plan_legs(action_fn)
        assert legs[0]["qty"] == 65  # FINNIFTY lot

    def test_build_legs_skips_malformed(self):
        """Legs without strike/opt_type are skipped."""
        from bridge.brain_bridge import BrainBridge

        bridge = BrainBridge(core_url="http://testserver")
        action = {
            "strategy": "iron_condor_nifty",
            "underlying": "NIFTY",
            "legs": [
                {"side": "SELL", "strike": 23050, "opt_type": "CE",
                 "expiry": "2026-10-01", "qty": 1},
                {"side": "BUY"},  # malformed — no strike
                {"side": "SELL", "strike": 22850, "opt_type": "",
                 "expiry": "2026-10-01", "qty": 1},  # no opt_type
            ],
        }
        legs = bridge._build_plan_legs(action)
        assert len(legs) == 1  # only the first leg survives

    def test_build_legs_for_single_leg_action(self):
        """Actions without explicit legs fall back to symbol+qty_lots."""
        from bridge.brain_bridge import BrainBridge

        bridge = BrainBridge(core_url="http://testserver")
        action = {
            "strategy": "nifty_cash_long",
            "underlying": "NIFTY",
            "symbol": "NIFTY",
            "side": "BUY",
            "qty_lots": 2,
            "segment": "nse_cm",
            "exchange": "NSE",
        }
        legs = bridge._build_plan_legs(action)
        assert len(legs) == 1
        assert legs[0]["symbol"] == "NIFTY"
        assert legs[0]["side"] == "BUY"
        assert legs[0]["qty"] == 150  # 2 lots × 75

    def test_parse_option_symbol_round_trip(self):
        """The bridge's symbol parser handles NIFTY options."""
        from bridge.brain_bridge import _parse_option_symbol

        u, exp, strike, opt = _parse_option_symbol("NIFTY01OCT2622950CE")
        assert u == "NIFTY"
        assert exp == "2026-10-01"
        assert strike == 22950.0
        assert opt == "CE"

        u, exp, strike, opt = _parse_option_symbol("BANKNIFTY30OCT2648000PE")
        assert u == "BANKNIFTY"
        assert exp == "2026-10-30"
        assert strike == 48000.0
        assert opt == "PE"


class TestBrainBridgeCoreIntegration:
    """The bridge submits plans via /api/plan (full chain)."""

    def test_quant_action_submitted_via_api_plan(self):
        """A quant_actions.json entry becomes an /api/plan submission
        that emits ORDER_PROPOSED events."""
        from fastapi.testclient import TestClient
        from bridge.brain_bridge import BrainBridge
        from system.core.api.server import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            quant = tmpdir / "quant_actions.json"
            quant.write_text(json.dumps({
                "actions": [{
                    "ts": "2026-09-29T23:00:00+05:30",
                    "strategy": "iron_condor_nifty",
                    "underlying": "NIFTY",
                    "rationale": "high VIX, range-bound",
                    "target": 50.0,
                    "stop": -30.0,
                    "legs": [
                        {"side": "SELL", "strike": 23050, "opt_type": "CE",
                         "expiry": "2026-10-01", "qty": 1},
                    ],
                }],
            }))
            db_path = str(tmpdir / "state.db")
            app = create_app(db_path)
            try:
                with TestClient(app) as client:
                    client.post(
                        "/api/market_tick",
                        params={"symbol": "NIFTY01OCT2623050CE",
                                "ltp": 100.0, "bid": 100.0, "ask": 100.5},
                    )
                    bridge = BrainBridge(
                        core_url="http://testserver",
                        quant_actions_path=str(quant),
                        interval=1,
                        http_session=client,
                    )
                    submitted = bridge.run_once()
                    assert submitted == 1, (
                        f"Expected 1 submission, got {submitted}"
                    )
                    # Verify ORDER_PROPOSED event was emitted
                    events = client.get(
                        "/api/events?types=order.proposed&limit=5"
                    ).json()["events"]
                    assert len(events) >= 1
                    assert events[-1]["payload"]["symbol"] == "NIFTY01OCT2623050CE"
                    # Verify the source file was marked consumed
                    doc = json.loads(quant.read_text(encoding="utf-8"))
                    assert doc["actions"][0].get("bridge_consumed") is True
                    assert doc["actions"][0].get("bridge_result", {}).get("ok") is True
            finally:
                app.state.store.close()

    def test_dedup_prevents_resubmission(self):
        """Calling run_once twice does NOT resubmit the same action."""
        from fastapi.testclient import TestClient
        from bridge.brain_bridge import BrainBridge
        from system.core.api.server import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            quant = tmpdir / "quant_actions.json"
            quant.write_text(json.dumps({
                "actions": [{
                    "ts": "2026-09-29T23:00:00+05:30",
                    "strategy": "iron_condor_nifty",
                    "underlying": "NIFTY",
                    "rationale": "high VIX",
                    "legs": [
                        {"side": "SELL", "strike": 23050, "opt_type": "CE",
                         "expiry": "2026-10-01", "qty": 1},
                    ],
                }],
            }))
            db_path = str(tmpdir / "state.db")
            app = create_app(db_path)
            try:
                with TestClient(app) as client:
                    client.post(
                        "/api/market_tick",
                        params={"symbol": "NIFTY01OCT2623050CE",
                                "ltp": 100.0, "bid": 100.0, "ask": 100.5},
                    )
                    bridge = BrainBridge(
                        core_url="http://testserver",
                        quant_actions_path=str(quant),
                        http_session=client,
                    )
                    # First run
                    n1 = bridge.run_once()
                    # Second run — should dedup
                    n2 = bridge.run_once()
                    assert n1 == 1
                    assert n2 == 0, (
                        f"Dedup failed: second run submitted {n2} actions"
                    )
                    # Only one ORDER_PROPOSED event total
                    events = client.get(
                        "/api/events?types=order.proposed&limit=10"
                    ).json()["events"]
                    assert len(events) == 1
            finally:
                app.state.store.close()

    def test_core_unavailable_skips_silently(self):
        """If the core is down, run_once returns 0 and doesn't raise."""
        from bridge.brain_bridge import BrainBridge

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            quant = tmpdir / "quant_actions.json"
            quant.write_text(json.dumps({
                "actions": [{
                    "ts": "2026-09-29T23:00:00+05:30",
                    "strategy": "iron_condor_nifty",
                    "underlying": "NIFTY",
                    "legs": [{"side": "SELL", "strike": 23050, "opt_type": "CE",
                              "expiry": "2026-10-01", "qty": 1}],
                }],
            }))
            bridge = BrainBridge(
                core_url="http://127.0.0.1:1",  # nothing listens here
                quant_actions_path=str(quant),
                http_session=type("S", (), {"post": staticmethod(
                    lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("down"))
                )})(),
            )
            # Should not raise
            assert bridge.run_once() == 0


class TestBrainBridgeSystemEnforced:
    """The bridge also processes system_enforced_action.json (LLM-silent
    fallback — see AGENTS.md '5 recurring issues' #1).
    """

    def test_system_enforced_action_submitted(self):
        """A system_enforced_action.json entry is submitted via /api/plan."""
        from fastapi.testclient import TestClient
        from bridge.brain_bridge import BrainBridge
        from system.core.api.server import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            sys_enf = tmpdir / "system_enforced_action.json"
            sys_enf.write_text(json.dumps({
                "ts": "2026-09-29T12:30:00+05:30",
                "actions": [{
                    "strategy": "directional_vertical",
                    "underlying": "NIFTY",
                    "rationale": "brain silent 60+ min, VIX collapse",
                    "legs": [
                        {"side": "BUY", "strike": 22900, "opt_type": "CE",
                         "expiry": "2026-10-01", "qty": 1},
                    ],
                }],
            }))
            db_path = str(tmpdir / "state.db")
            app = create_app(db_path)
            try:
                with TestClient(app) as client:
                    client.post(
                        "/api/market_tick",
                        params={"symbol": "NIFTY01OCT2622900CE",
                                "ltp": 50.0, "bid": 50.0, "ask": 50.5},
                    )
                    bridge = BrainBridge(
                        core_url="http://testserver",
                        sys_enforced_path=str(sys_enf),
                        http_session=client,
                    )
                    submitted = bridge.run_once()
                    assert submitted == 1
                    doc = json.loads(sys_enf.read_text(encoding="utf-8"))
                    assert doc.get("bridge_consumed") is True
            finally:
                app.state.store.close()


class TestBrainBridgeHealth:
    """The bridge checks core health before processing."""

    def test_health_returns_false_when_core_down(self):
        """health() returns False when /healthz is unreachable."""
        from bridge.brain_bridge import BrainBridge

        bridge = BrainBridge(core_url="http://127.0.0.1:1")
        assert bridge.health() is False

    def test_health_returns_true_when_core_up(self):
        """health() returns True when /healthz returns 200."""
        from fastapi.testclient import TestClient
        from bridge.brain_bridge import BrainBridge
        from system.core.api.server import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "state.db")
            app = create_app(db_path)
            try:
                with TestClient(app) as client:
                    bridge = BrainBridge(
                        core_url="http://testserver",
                        http_session=client,
                    )
                    assert bridge.health() is True
            finally:
                app.state.store.close()