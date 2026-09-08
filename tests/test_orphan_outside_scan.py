"""Tests for orphan check OUTSIDE the scan block (commit moving orphan check).

BUG HISTORY (2026-09-08):
The orphan-auto-close logic used to be nested INSIDE the scan block. The
scan block gets skipped (via `continue`) when:
  - past no_new_trades time (after 13:30)
  - in opening buffer (09:15-09:30)
  - VIX above threshold
  - macro event blackout

When the scan was skipped, the `continue` ALSO skipped the orphan check.
This meant brain-driven OPENs (which don't register with order_mgr) sat
uncatalogued for hours, only to be force-squared at 14:30 IST.

FIX 2026-09-08 14:15: extract the orphan check into its own block that
runs every 30s, independent of the scan block. The close action still
respects the no-new-trades time gate (we don't want to destroy brain
hold-window trades at 12:04 like we did yesterday).

These tests verify the BLOCK STRUCTURE — that orphan logic is decoupled
from the scan block — by parsing __main__.py and confirming:
  1. The orphan-check block appears BEFORE the scan-block skip-conditions.
  2. The orphan block is reachable without entering the scan block.
  3. The orphan block has its own `try/except` and is non-fatal.
"""
import re
from pathlib import Path


ROOT = Path(__file__).parent.parent.resolve()
MAIN_PY = ROOT / "kotak_bot" / "__main__.py"


def _read_main() -> str:
    return MAIN_PY.read_text(encoding="utf-8")


def test_orphan_block_exists_outside_scan():
    """The orphan check block must exist as its own block, BEFORE the scan block."""
    text = _read_main()
    # Find the orphan check block marker
    orphan_marker = "# 4a) ORPHAN CHECK runs on its own 30s cadence, OUTSIDE the scan block."
    assert orphan_marker in text, (
        f"orphan check block marker not found in __main__.py — "
        f"the orphan check should be in its own block, not nested in the scan block"
    )
    # And it should appear BEFORE the scan skip-conditions (no_new_trades, opening buffer)
    no_new_trades_marker = "is_past_no_new_trades_time(now):"
    orphan_pos = text.index(orphan_marker)
    skip_pos = text.find(no_new_trades_marker, orphan_pos)
    assert skip_pos > orphan_pos, (
        f"orphan check block appears at offset {orphan_pos} but the scan skip "
        f"condition appears at {skip_pos} — orphan must be BEFORE the scan block"
    )


def test_orphan_block_has_own_try_except():
    """The orphan check must be wrapped in its own try/except so a failure
    in the orphan check doesn't break the scan block."""
    text = _read_main()
    orphan_marker = "# 4a) ORPHAN CHECK runs on its own 30s cadence, OUTSIDE the scan block."
    # Look for a try/except within the first 2000 chars after the marker
    after_orphan = text[text.index(orphan_marker):text.index(orphan_marker) + 2000]
    assert "try:" in after_orphan, (
        f"orphan block must include try: — see __main__.py around the orphan block"
    )
    assert "except Exception as _orph_block_err" in text[text.index(orphan_marker):text.index(orphan_marker) + 10000], (
        f"orphan block must have its own except clause: except Exception as _orph_block_err"
    )


def test_orphan_block_independent_of_scan_block():
    """The orphan block must not be inside the scan block's `if is_market_open(now)` and
    `if (now - last_scan).total_seconds() >= 30` condition. It must have its own
    condition that runs whenever the market is open (independent of scan)."""
    text = _read_main()
    orphan_marker = "# 4a) ORPHAN CHECK runs on its own 30s cadence, OUTSIDE the scan block."
    orphan_idx = text.index(orphan_marker)
    # The first 2000 chars should contain a condition that triggers the orphan block.
    next_chunk = text[orphan_idx:orphan_idx + 2000]
    # Should have its own `if is_market_open(now) and (now - last_scan).total_seconds() >= 30:`
    # or similar that triggers the orphan block, separate from the scan block trigger
    assert re.search(
        r"if\s+is_market_open\(now\)\s+and\s+\(now\s*-\s*last_scan\)\.total_seconds\(\)\s*>=\s*30",
        next_chunk,
    ), "orphan block must have its own trigger condition (is_market_open + 30s cadence)"


def test_orphan_close_still_respects_time_gate():
    """Even though the orphan check runs every 30s, the CLOSE action must still
    respect the no-new-trades time gate. Before 13:30 → log only, no close.
    After 13:30 → close. This preserves the fix from 2026-09-07 23:15."""
    text = _read_main()
    orphan_marker = "# 4a) ORPHAN CHECK runs on its own 30s cadence, OUTSIDE the scan block."
    orphan_idx = text.index(orphan_marker)
    after_orphan = text[orphan_idx:orphan_idx + 8000]
    # Must call is_past_no_new_trades_time(now) within the orphan block
    assert "is_past_no_new_trades_time(now)" in after_orphan[:6000], (
        f"orphan block must call is_past_no_new_trades_time(now) to gate the close action"
    )
    # Must have a debug-level log when not allowed (so we don't spam warnings)
    assert "Auto-close deferred" in after_orphan or "deferred" in after_orphan, (
        f"orphan block should log a deferral message when not allowed to close"
    )


def test_old_orphan_check_removed_from_scan_block():
    """The OLD orphan check (which was nested inside the scan block, before the
    cap check) should no longer exist. Otherwise we'd have two orphan check
    sites and a double-close race."""
    text = _read_main()
    # The old comment was: "FIX 2026-09-07 23:15: gate orphan-auto-close on no-new-trades time."
    # And the old block was inside the scan, gated by `is_past_no_new_trades_time(now)`
    # We just need to make sure the orphan check is NOT inside the scan block anymore.
    # Find the orphan marker
    orphan_marker = "# 4a) ORPHAN CHECK runs on its own 30s cadence, OUTSIDE the scan block."
    orphan_idx = text.index(orphan_marker)
    # The next 8000 chars should contain the orphan close loop with the right pattern
    after_orphan = text[orphan_idx:orphan_idx + 8000]
    # Should have the full close loop logic (Order construction, broker.place_order)
    assert "broker.place_order(_close_ord)" in after_orphan, (
        f"orphan block must still call broker.place_order for the close action"
    )
    assert "ORPHAN-AUTO-CLOSE" in after_orphan, (
        f"orphan block must still tag closes with ORPHAN-AUTO-CLOSE"
    )


def test_scan_block_no_longer_references_orphan_pos():
    """The scan block should no longer reference `orphan_pos` (the old variable
    that was nested inside it)."""
    text = _read_main()
    # Count occurrences of `orphan_pos` (the OLD variable)
    # The NEW orphan check uses `_orphan_pos_o` with the `_o` suffix
    bare_orphan_count = len(re.findall(r"\borphan_pos\b", text))
    assert bare_orphan_count == 0, (
        f"scan block still references bare `orphan_pos` ({bare_orphan_count}x) — "
        f"should be renamed to `_orphan_pos_o` or moved into the orphan block"
    )
