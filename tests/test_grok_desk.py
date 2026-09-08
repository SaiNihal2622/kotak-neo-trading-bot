"""Tests for the 6-role Grok Bot Desk (scripts/grok_desk.py).

Verifies the structural design without making real LLM calls:
  1. All 6 system prompts are present and non-empty
  2. Each role's data-assembly function returns a string
  3. The HEAD prompt explicitly mentions "QUIET DAY" (default output)
  4. should_alert() returns False for QUIET DAY output
  5. should_alert() returns True for non-empty non-QUIET output
  6. The 6 role functions are independently callable
  7. DeskOutput has all 6 fields
  8. State file is written when save_state() is called

Real LLM calls are exercised manually via `python scripts/run_grok_desk.py`.
"""
from pathlib import Path
import json
import sys
import os

# Ensure project root is on path so `from scripts import grok_desk` works
ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from scripts import grok_desk  # noqa: E402


# ---------- structural tests ----------

def test_all_6_system_prompts_present():
    """All 6 system prompts must be defined and non-empty."""
    prompts = {
        "scanner": grok_desk.SYSTEM_SCANNER,
        "hunter": grok_desk.SYSTEM_HUNTER,
        "news": grok_desk.SYSTEM_NEWS,
        "whales": grok_desk.SYSTEM_WHALES,
        "risk": grok_desk.SYSTEM_RISK,
        "head": grok_desk.SYSTEM_HEAD,
    }
    for name, p in prompts.items():
        assert p, f"{name} system prompt is empty"
        assert len(p) > 50, f"{name} system prompt too short: {len(p)} chars"


def test_head_prompt_mentions_quiet_day():
    """The head-of-desk prompt must default to QUIET DAY to enforce the
    'speak rarely' philosophy from the original Grok Bot guide."""
    assert "QUIET DAY" in grok_desk.SYSTEM_HEAD, (
        "head-of-desk prompt should mention QUIET DAY as default output — "
        "this is the central design from the Grok Bot guide"
    )


def test_risk_prompt_outranks_everyone():
    """The risk prompt should claim authority ('outrank everyone')."""
    assert "outrank" in grok_desk.SYSTEM_RISK.lower(), (
        "risk prompt should claim authority over the other desks"
    )


def test_each_role_is_independently_callable():
    """All 6 role functions must be defined as callables."""
    for fn_name in ("run_scanner", "run_hunter", "run_news", "run_whales", "run_risk", "run_head"):
        fn = getattr(grok_desk, fn_name, None)
        assert callable(fn), f"{fn_name} not defined or not callable"


def test_desk_output_has_all_6_fields():
    """DeskOutput must have scanner, hunter, news, whales, risk, head."""
    out = grok_desk.DeskOutput()
    for field in ("scanner", "hunter", "news", "whales", "risk", "head"):
        assert hasattr(out, field), f"DeskOutput missing field {field}"
    assert hasattr(out, "cycle_ts")
    assert hasattr(out, "duration_sec")
    assert hasattr(out, "error")


# ---------- data assembly tests (no LLM) ----------

def test_opt_chain_summary_returns_string():
    """_opt_chain_summary must return a string for known and unknown symbols."""
    s1 = grok_desk._opt_chain_summary("NIFTY")
    assert isinstance(s1, str)
    s2 = grok_desk._opt_chain_summary("UNKNOWN_SYMBOL_XYZ")
    assert isinstance(s2, str)


def test_levels_summary_returns_string():
    s = grok_desk._levels_summary()
    assert isinstance(s, str)


def test_oi_summary_returns_string():
    s = grok_desk._oi_summary()
    assert isinstance(s, str)


def test_news_summary_returns_string():
    s = grok_desk._news_summary()
    assert isinstance(s, str)


def test_position_summary_returns_string():
    s = grok_desk._position_summary()
    assert isinstance(s, str)


# ---------- should_alert tests (no LLM) ----------

def test_should_alert_false_for_quiet_day():
    """QUIET DAY is the default output → no Telegram alert."""
    assert grok_desk.should_alert("QUIET DAY") is False
    assert grok_desk.should_alert("quiet day - nothing material today") is False
    assert grok_desk.should_alert("  QUIET DAY  ") is False


def test_should_alert_false_for_empty():
    assert grok_desk.should_alert("") is False
    assert grok_desk.should_alert("   ") is False
    assert grok_desk.should_alert(None) is False


def test_should_alert_true_for_real_message():
    """When head-of-desk actually speaks, alert."""
    msg = (
        "NIFTY broke 23800 with FII buying +3000 cr and DII selling -2000 cr. "
        "Risk APPROVED. Watch the 23900 retest; if it holds, momentum long."
    )
    assert grok_desk.should_alert(msg) is True


# ---------- save_state test (no LLM) ----------

def test_save_state_writes_file(tmp_path: Path, monkeypatch):
    """save_state() should write a JSON file to data_cache/grok_desk_state.json."""
    # monkeypatch the paths to a tmp dir
    monkeypatch.setattr(grok_desk, "DCACHE", tmp_path)
    monkeypatch.setattr(grok_desk, "STATE_PATH", tmp_path / "grok_desk_state.json")
    monkeypatch.setattr(grok_desk, "HISTORY_PATH", tmp_path / "grok_desk_history.jsonl")

    out = grok_desk.DeskOutput(
        scanner="NIFTY: top OI build-up at 24000 CE",
        hunter="NIFTY range 23700-23900, watching 23800 break",
        news="RBI hawkish tone - PRIMARY",
        whales="FII net long +1500 cr",
        risk="APPROVED (1.2% of capital)",
        head="BREAKOUT WATCH: NIFTY 23800 break with FII flow. Invalidation: back below 23750.",
        cycle_ts="2026-09-08T10:00:00+05:30",
        duration_sec=12.3,
    )
    grok_desk.save_state(out)

    assert grok_desk.STATE_PATH.exists()
    state = json.loads(grok_desk.STATE_PATH.read_text(encoding="utf-8"))
    assert state["scanner"] == "NIFTY: top OI build-up at 24000 CE"
    assert state["head"] == out.head
    assert state["duration_sec"] == 12.3

    assert grok_desk.HISTORY_PATH.exists()
    history = grok_desk.HISTORY_PATH.read_text(encoding="utf-8").strip().split("\n")
    assert len(history) == 1
    hist = json.loads(history[0])
    assert hist["head"] == out.head


# ---------- LLM connectivity smoke test (only if key is present) ----------

def test_minimax_reachable_if_key_set(monkeypatch):
    """If MINIMAX_LLM_API_KEY is set, the API must respond successfully.
    This is the 'check' part of the user's request — confirm our model
    can replace Grok for the same 6-role architecture."""
    from dotenv import load_dotenv
    env_path = ROOT / "config" / "credentials.env"
    if env_path.exists():
        load_dotenv(str(env_path))
    api_key = os.environ.get("MINIMAX_LLM_API_KEY", "")
    if not api_key:
        # Skip the test if no key is configured locally
        import pytest
        pytest.skip("MINIMAX_LLM_API_KEY not set in env (skip live API test)")
    # Monkey-patch the module to use the loaded key
    monkeypatch.setattr(grok_desk, "LLM_API_KEY", api_key)
    out = grok_desk._call_minimax(
        "You are a precise analyst. Return ONLY valid JSON, no prose.",
        'Reply with the JSON object {"ok": true}.',
        max_tokens=100,
        timeout=20,
    )
    assert "ok" in out.lower() or "true" in out.lower(), f"unexpected response: {out[:200]}"
