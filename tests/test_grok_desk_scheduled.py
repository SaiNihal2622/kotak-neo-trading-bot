"""Tests that verify the Grok Bot Desk is wired into the brain's in-process
scheduler. Confirms the new code path is in place without actually running
the LLM (which would be slow and rate-limited).
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
QS = ROOT / "scripts" / "quant_service.py"


def _read() -> str:
    return QS.read_text(encoding="utf-8")


def test_grok_desk_scheduler_wired():
    """The brain must have a 15-min scheduler that runs scripts/run_grok_desk.py.
    FIX 2026-09-08 22:35: now runs 24/7 (was: only during NSE market hours)."""
    text = _read()
    assert "last_grok_desk_ts" in text, "last_grok_desk_ts not declared in quant_service.py"
    # The periodic check: every 900s (15 min), 24/7 (no is_market_hours gate)
    pattern = re.compile(
        r"datetime\.now\(\)\.timestamp\(\)\s*-\s*last_grok_desk_ts\s*>\s*900"
    )
    assert pattern.search(text), (
        "Grok Desk 15-min periodic check not wired into watch_loop. "
        "Should be: 'datetime.now().timestamp() - last_grok_desk_ts > 900' "
        "(24/7, no is_market_hours gate — runs overnight research mode too)"
    )


def test_grok_desk_subprocess_call():
    """The periodic check must call scripts/run_grok_desk.py via _scheduled_subprocess."""
    text = _read()
    assert "scripts/run_grok_desk.py" in text, (
        "scripts/run_grok_desk.py not referenced from quant_service.py"
    )
    assert "grok-desk" in text, (
        "Grok Desk label 'grok-desk' not found in quant_service.py. "
        "Expected: _scheduled_subprocess('scripts/run_grok_desk.py', 'grok-desk', ...)"
    )


def test_grok_desk_global_declaration():
    """The new timestamp var must be in the global declaration block to
    avoid UnboundLocalError (5th shadow-import bug class — already
    documented in AGENTS.md)."""
    text = _read()
    # find the global block that contains last_periodic_scan_ts, last_global_check_ts
    g = re.search(
        r"global\s+last_periodic_scan_ts,\s*last_global_check_ts[^\n]*\n\s*global\s+last_grok_desk_ts",
        text,
    )
    assert g, (
        "last_grok_desk_ts NOT in the global declaration block. "
        "Without `global last_grok_desk_ts`, the assignment inside watch_loop "
        "would shadow the module-level binding and cause UnboundLocalError. "
        "This is the 5th shadow-import bug class."
    )


def test_grok_desk_timestamp_var_declared():
    """last_grok_desk_ts must be declared at module level (where other ts vars are)."""
    text = _read()
    # match a line like: last_grok_desk_ts = 0 ...
    assert re.search(r"^last_grok_desk_ts\s*=\s*0", text, re.MULTILINE), (
        "last_grok_desk_ts = 0 not declared at module level. "
        "Should be alongside last_chain_refresh_ts, last_periodic_scan_ts, etc."
    )


def test_grok_desk_uses_scheduled_subprocess_not_inline():
    """The Grok Desk must run as a subprocess via _scheduled_subprocess, not
    inline. This isolates the 6 LLM calls (~30s latency) from the brain's
    1Hz main loop."""
    text = _read()
    # find the line where grok-desk is referenced
    match = re.search(
        r'_scheduled_subprocess\(\s*"scripts/run_grok_desk\.py"[^)]*\)',
        text,
    )
    assert match, "Grok Desk should be called via _scheduled_subprocess, not inline"


def test_grok_desk_logs_sched_label():
    """For log observability, the scheduled subprocess should use a clear label."""
    text = _read()
    # the call should be _scheduled_subprocess("scripts/run_grok_desk.py", "grok-desk", ...)
    assert re.search(r'_scheduled_subprocess\(\s*"scripts/run_grok_desk\.py",\s*"grok-desk"', text), (
        "Grok Desk scheduled_subprocess call should use 'grok-desk' as the log label"
    )
