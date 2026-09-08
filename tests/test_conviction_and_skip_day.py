"""Tests for conviction-based sizing + SKIP_DAY decision type."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


# ---------- conviction-based sizing tests ----------

def test_normalize_decision_extracts_conviction():
    """_normalize_decision should extract `conviction: 0-100` from the LLM output."""
    from scripts.quant_service import _normalize_decision
    d = {
        "type": "OPEN",
        "underlying": "NIFTY",
        "conviction": 80,
        "legs": [{"side": "BUY", "qty": 5, "strike": 24000, "opt_type": "PE"}],
    }
    out = _normalize_decision(d)
    assert out["conviction"] == 80, f"conviction not extracted: {out}"


def test_normalize_decision_falls_back_to_confidence():
    """If `conviction` is missing, fall back to `confidence: 0-1` × 100."""
    from scripts.quant_service import _normalize_decision
    d = {
        "type": "OPEN",
        "underlying": "NIFTY",
        "confidence": 0.65,
        "legs": [{"side": "BUY", "qty": 3, "strike": 24000, "opt_type": "PE"}],
    }
    out = _normalize_decision(d)
    assert out["conviction"] == 65, f"confidence fallback not working: {out}"


def test_normalize_decision_default_conviction_zero():
    """If neither conviction nor confidence is given, default to 0."""
    from scripts.quant_service import _normalize_decision
    d = {
        "type": "OPEN",
        "underlying": "NIFTY",
        "legs": [{"side": "BUY", "qty": 3, "strike": 24000, "opt_type": "PE"}],
    }
    out = _normalize_decision(d)
    assert out["conviction"] == 0


def test_conviction_scales_qty_in_write_decision(tmp_path, monkeypatch):
    """write_decision should scale leg qty by (conviction/100)."""
    from scripts import quant_service
    from datetime import datetime, timezone, timedelta
    # Redirect ACTIONS to tmp
    actions_path = tmp_path / "quant_actions.json"
    decisions_path = tmp_path / "decisions.jsonl"
    monkeypatch.setattr(quant_service, "ACTIONS", actions_path)
    monkeypatch.setattr(quant_service, "DECISIONS", str(decisions_path))
    monkeypatch.setattr(quant_service, "log", lambda x: None)  # silence
    # Mock datetime.now() to return a market-hours time (Wed 10:00 IST)
    ist = timezone(timedelta(hours=5, minutes=30))
    fake_now = datetime(2026, 9, 9, 10, 0, 0, tzinfo=ist)  # Wednesday
    class FakeDatetime:
        @classmethod
        def now(cls, tz=None):
            return fake_now if tz is None else fake_now.astimezone(tz)
    monkeypatch.setattr(quant_service, "datetime", FakeDatetime)
    # Decision: OPEN with conviction=50, qty=4
    decision = {
        "type": "OPEN",
        "underlying": "NIFTY",
        "strategy": "bear_put",
        "conviction": 50,
        "legs": [
            {"side": "BUY", "qty": 4, "strike": 24000, "opt_type": "PE"},
            {"side": "SELL", "qty": 4, "strike": 24100, "opt_type": "PE"},
        ],
        "rationale": "test",
    }
    quant_service.write_decision(decision)
    # The action should be written with qty scaled: 4 * 50/100 = 2
    assert actions_path.exists()
    ad = json.loads(actions_path.read_text(encoding="utf-8"))
    assert len(ad["actions"]) == 1
    a = ad["actions"][0]
    assert a["legs"][0]["qty"] == 2, f"qty not scaled by conviction: {a['legs']}"
    assert a["legs"][1]["qty"] == 2


def test_conviction_scales_qty_with_min_1_lot():
    """If conviction × qty < 1, use 1 lot (don't go to 0)."""
    from scripts import quant_service
    from datetime import datetime, timezone, timedelta
    ist = timezone(timedelta(hours=5, minutes=30))
    fake_now = datetime(2026, 9, 9, 10, 0, 0, tzinfo=ist)
    class FakeDatetime:
        @classmethod
        def now(cls, tz=None):
            return fake_now if tz is None else fake_now.astimezone(tz)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        actions_path = Path(tmp) / "quant_actions.json"
        decisions_path = Path(tmp) / "decisions.jsonl"
        original_actions = quant_service.ACTIONS
        original_decisions = quant_service.DECISIONS
        original_datetime = quant_service.datetime
        quant_service.ACTIONS = actions_path
        quant_service.DECISIONS = str(decisions_path)
        quant_service.datetime = FakeDatetime
        quant_service.log = lambda x: None
        try:
            # Decision: conviction=20, qty=2 → 0.4 → min 1 lot
            decision = {
                "type": "OPEN",
                "underlying": "NIFTY",
                "strategy": "x",
                "conviction": 20,
                "legs": [{"side": "BUY", "qty": 2, "strike": 24000, "opt_type": "PE"}],
                "rationale": "test",
            }
            quant_service.write_decision(decision)
            ad = json.loads(actions_path.read_text(encoding="utf-8"))
            assert ad["actions"][0]["legs"][0]["qty"] == 1, (
                f"min 1 lot not enforced: {ad['actions'][0]['legs'][0]['qty']}"
            )
        finally:
            quant_service.ACTIONS = original_actions
            quant_service.DECISIONS = original_decisions
            quant_service.datetime = original_datetime


def test_conviction_max_10_lot_cap_still_applies():
    """The 10-lot hard cap from 2026-09-02 still applies even with high conviction."""
    from scripts import quant_service
    from datetime import datetime, timezone, timedelta
    ist = timezone(timedelta(hours=5, minutes=30))
    fake_now = datetime(2026, 9, 9, 10, 0, 0, tzinfo=ist)
    class FakeDatetime:
        @classmethod
        def now(cls, tz=None):
            return fake_now if tz is None else fake_now.astimezone(tz)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        actions_path = Path(tmp) / "quant_actions.json"
        decisions_path = Path(tmp) / "decisions.jsonl"
        original_actions = quant_service.ACTIONS
        original_decisions = quant_service.DECISIONS
        original_datetime = quant_service.datetime
        quant_service.ACTIONS = actions_path
        quant_service.DECISIONS = str(decisions_path)
        quant_service.datetime = FakeDatetime
        quant_service.log = lambda x: None
        try:
            # Decision: conviction=100, qty=20 → scaled to 10 (cap)
            decision = {
                "type": "OPEN",
                "underlying": "NIFTY",
                "strategy": "x",
                "conviction": 100,
                "legs": [{"side": "BUY", "qty": 20, "strike": 24000, "opt_type": "PE"}],
                "rationale": "test",
            }
            quant_service.write_decision(decision)
            ad = json.loads(actions_path.read_text(encoding="utf-8"))
            assert ad["actions"][0]["legs"][0]["qty"] == 10, (
                f"10-lot hard cap not enforced: {ad['actions'][0]['legs'][0]['qty']}"
            )
        finally:
            quant_service.ACTIONS = original_actions
            quant_service.DECISIONS = original_decisions
            quant_service.datetime = original_datetime


# ---------- SKIP_DAY tests ----------

def test_skip_day_writes_flag_file(tmp_path, monkeypatch):
    """write_decision with type=SKIP_DAY should write data_cache/_skip_day.json."""
    from scripts import quant_service
    from datetime import datetime, timezone, timedelta
    ist = timezone(timedelta(hours=5, minutes=30))
    fake_now = datetime(2026, 9, 9, 10, 0, 0, tzinfo=ist)
    class FakeDatetime:
        @classmethod
        def now(cls, tz=None):
            return fake_now if tz is None else fake_now.astimezone(tz)
    from pathlib import Path as RealPath
    real_write_text = RealPath.write_text
    skip_path = tmp_path / "_skip_day.json"
    # Path comparison is OS-dependent. Use a normalized string.
    skip_path_str = str(skip_path).replace("\\", "/")

    # Capture all writes
    written_paths = []
    def fake_write_text(self, *args, **kwargs):
        written_paths.append(str(self).replace("\\", "/"))
        if "_skip_day.json" in str(self):
            return real_write_text(skip_path, *args, **kwargs)
        return real_write_text(self, *args, **kwargs)
    monkeypatch.setattr(RealPath, "write_text", fake_write_text)
    monkeypatch.setattr(quant_service, "datetime", FakeDatetime)
    quant_service.log = lambda x: None

    decision = {
        "type": "SKIP_DAY",
        "rationale": "VIX spike, no clear setup, FII selling 50k cr",
    }
    quant_service.write_decision(decision)
    # Find which path was actually written
    skip_writes = [p for p in written_paths if "_skip_day.json" in p]
    assert skip_writes, f"SKIP_DAY did not write to _skip_day.json. Writes: {written_paths}"
    assert skip_path.exists(), f"SKIP_DAY flag file not written. Writes: {written_paths}"
    d = json.loads(skip_path.read_text(encoding="utf-8"))
    assert "reason" in d
    assert "VIX spike" in d["reason"]
    assert "expires_at" in d


def test_skip_day_does_not_write_to_actions(tmp_path, monkeypatch):
    """SKIP_DAY should NOT write to quant_actions.json (only to the skip flag)."""
    from scripts import quant_service
    actions_path = tmp_path / "quant_actions.json"
    decisions_path = tmp_path / "decisions.jsonl"
    monkeypatch.setattr(quant_service, "ACTIONS", actions_path)
    monkeypatch.setattr(quant_service, "DECISIONS", str(decisions_path))
    quant_service.log = lambda x: None
    # monkeypatch Path("data_cache/_skip_day.json") to tmp_path
    from pathlib import Path as RealPath
    real_write_text = RealPath.write_text
    skip_path = tmp_path / "_skip_day.json"
    def fake_write_text(self, *args, **kwargs):
        if str(self) == "data_cache/_skip_day.json":
            return real_write_text(skip_path, *args, **kwargs)
        return real_write_text(self, *args, **kwargs)
    monkeypatch.setattr(RealPath, "write_text", fake_write_text)
    decision = {"type": "SKIP_DAY", "rationale": "test"}
    quant_service.write_decision(decision)
    assert not actions_path.exists(), "SKIP_DAY should NOT write to quant_actions.json"


# ---------- bot-side skip_day honor ----------

def test_bot_honors_skip_day():
    """The bot's main loop must check data_cache/_skip_day.json before scanning."""
    from pathlib import Path
    main_py = (ROOT / "kotak_bot" / "__main__.py").read_text(encoding="utf-8")
    assert "_skip_day.json" in main_py, (
        "bot's main loop must reference _skip_day.json"
    )
    assert "_skip_day_active" in main_py, (
        "bot's main loop must check _skip_day_active"
    )
