"""Tests for the broken-condor emergency close + Phase 4 removal.

The original broken-condor bug from 2026-09-29 caused a -Rs.10,720 loss:
1. SELL leg auto-snap couldn't fire (PaperClient had 0 live ticks)
2. CLOSE_ALL orphan fallback only ran if order_mgr had 0 trades to close
3. No detector for broken-condor state (BUYs filled but SELLs didn't)

The original fix (FIX 2026-09-29 14:00) added:
- Detector inside QUANT-ACTION OPEN
- Top-of-loop handler to read _broken_condor.json and close orphans
- Plan-handler to do the same in force-action path

Phase 3 (2026-09-29): bot routes through /api/plan (core's pre-flight).
  Pre-flight validates the WHOLE plan atomically. With PaperClient's
  synchronous fills, _placed always equals len(_qa_legs) or 0. The
  broken-condor state is structurally impossible in paper mode.

Phase 4 (2026-09-29): broken-condor detector + top-of-loop + plan-handler
  REMOVED from __main__.py. They are now unreachable. This test verifies
  the cleanup is real and the bot still parses.

The CLOSE_ALL orphan fallback (the original FIX 2026-09-29 14:00 inside
the force-action CLOSE_ALL block) stays — that's still defense-in-depth
when an explicit user action requests position cleanup.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestCLOSEALLOrphanFallbackStillPresent:
    """The CLOSE_ALL orphan fallback (FIX 2026-09-29 14:00) is still in
    __main__.py — it's the one broken-condor-era fix that survives Phase 4
    because it covers the explicit-user-action case (Mavis sends
    CLOSE_ALL, bot must close broker positions even if order_mgr is empty).
    """

    def test_close_all_orphan_check_unconditional(self):
        """Read the source — confirm the fallback is now unconditional."""
        main_py = (ROOT / "kotak_bot" / "__main__.py").read_text(encoding="utf-8")
        # Find the CLOSE_ALL block
        idx = main_py.find('if _fa_action == "CLOSE_ALL":')
        assert idx > 0
        # Get the next 2000 chars (CLOSE_ALL handler block)
        block = main_py[idx:idx + 2000]
        # The orphan fallback must use 'if True:' (unconditional), not 'if n == 0:'
        # Look for the comment about FIX 2026-09-29 14:00
        assert "FIX 2026-09-29 14:00: ALWAYS check broker positions" in block, (
            "CLOSE_ALL must always check broker positions (FIX 2026-09-29 14:00)"
        )
        # The unconditional `if True:` should appear right after the orphan-fallback comment
        assert "if True:" in block, (
            "After the FIX, the orphan fallback condition must be `if True:` "
            "(unconditional), not `if n == 0:`"
        )
        # Old broken logic must NOT be present
        # Find the orphan fallback block
        n_closeall_idx = main_py.find('if _fa_action == "CLOSE_ALL":')
        orphan_section = main_py[n_closeall_idx:n_closeall_idx + 2500]
        assert "if n == 0:" not in orphan_section.split("FIX 2026-09-29 14:00")[1], (
            "The orphan fallback must NOT use `if n == 0:` after the fix"
        )


class TestBrokenCondorHandlersRemoved:
    """Phase 4 (2026-09-29): the broken-condor detector + top-of-loop
    handler + plan-handler are REMOVED from __main__.py. Pre-flight +
    atomic paper fills make them unreachable.
    """

    def test_broken_condor_top_loop_handler_removed(self):
        """The top-of-loop handler (FIX 2026-09-29 14:25) is REMOVED."""
        main_py = (ROOT / "kotak_bot" / "__main__.py").read_text(encoding="utf-8")
        # Find the run_paper() function and its main loop
        run_paper_idx = main_py.find("def run_paper() -> None:")
        assert run_paper_idx > 0, "run_paper() must exist in __main__.py"
        loop_idx = main_py.find("while True:", run_paper_idx)
        assert loop_idx > 0, "run_paper() must contain a `while True:` loop"
        # Get the next 3500 chars (start of the loop)
        loop_start = main_py[loop_idx:loop_idx + 3500]
        # Must NOT contain the top-of-loop handler
        assert "FIX 2026-09-29 14:25: broken-condor emergency close (top of loop)" not in loop_start, (
            "Top-of-loop handler must be REMOVED in Phase 4 — pre-flight makes it unreachable"
        )
        # But the run_paper() entry comment about the removal must exist
        assert "broken-condor top-of-loop handler REMOVED" in loop_start, (
            "Phase 4 marker comment about top-of-loop removal must exist"
        )

    def test_broken_condor_plan_handler_removed(self):
        """The plan-handler (FIX 2026-09-29 14:00 in force-action) is REMOVED."""
        main_py = (ROOT / "kotak_bot" / "__main__.py").read_text(encoding="utf-8")
        # The plan-handler was a multi-line block reading _broken_condor.json
        # inside the mavis_force_action.json handler. After Phase 4, the only
        # _bc_path / _bc variables in that block should not exist.
        # Use the comment marker to find what's expected
        assert "broken-condor plan-handler REMOVED" in main_py, (
            "Phase 4 marker comment about plan-handler removal must exist"
        )
        # The plan-handler block had a comment starting with "FIX 2026-09-29 14:00: broken-condor emergency close."
        # After Phase 4 that exact comment is gone (replaced with the REMOVED marker).
        # Count occurrences: should be exactly 1 (the detector, also removed → 0).
        assert main_py.count("FIX 2026-09-29 14:00: broken-condor emergency close.") == 0, (
            "Plan-handler block comment must be replaced with Phase 4 marker"
        )

    def test_broken_condor_detector_removed(self):
        """The detector inside QUANT-ACTION OPEN (FIX 2026-09-29 14:00) is REMOVED."""
        main_py = (ROOT / "kotak_bot" / "__main__.py").read_text(encoding="utf-8")
        # The detector wrote _broken_condor.json when _placed < len(_qa_legs).
        # After Phase 4, the detector comment + condition are gone.
        assert "FIX 2026-09-29 14:00: broken-condor detector" not in main_py, (
            "Broken-condor detector must be REMOVED in Phase 4"
        )
        # The Phase 4 marker comment must exist instead
        assert "broken-condor detector REMOVED" in main_py, (
            "Phase 4 marker comment about detector removal must exist"
        )
        # The detector condition `_placed > 0 and _placed < len(_qa_legs)` is gone
        # BUT: the legs_placed= summary line still has the substring "placed" — narrow the check
        # Look for the exact detector predicate in the context of broken-condor
        assert "_placed > 0 and _placed < len(_qa_legs) and len(_qa_legs) >= 3" not in main_py, (
            "Detector predicate must be REMOVED"
        )

    def test_no_broken_condor_marker_writes_remain(self):
        """No code path should write data_cache/_broken_condor.json after Phase 4.

        The string may still appear in PHASE 4 marker comments (explaining what
        was removed). We assert that it never appears as a code path: i.e. no
        file write or read against that path. We check by looking for the
        pattern 'with open' / 'Path(' / 'unlink' / '.exists()' / '.write_text'
        referencing the marker.
        """
        main_py = (ROOT / "kotak_bot" / "__main__.py").read_text(encoding="utf-8")
        # The marker filename as a code reference would appear inside Path(),
        # open(), or .write_text() calls. Strip comments and docstrings first
        # to avoid false positives in PHASE 4 marker explanations.
        import re
        # Remove triple-quoted strings (docstrings) — both """ and '''
        stripped = re.sub(r'\"\"\"[\s\S]*?\"\"\"', '', main_py)
        stripped = re.sub(r"\'\'\'[\s\S]*?\'\'\'", '', stripped)
        # Remove single-line comments
        stripped = re.sub(r'#[^\n]*', '', stripped)
        assert "_broken_condor.json" not in stripped, (
            "No CODE should reference _broken_condor.json after Phase 4 "
            "(comments are stripped before checking)"
        )


class TestBrokenCondorMarkerSchemaStillDocumented:
    """The marker schema is preserved as documentation. If/when we go live,
    this can be re-added at the core layer.
    """

    def test_broken_condor_marker_format(self, tmp_path):
        """Document the marker schema — what fields a future live-mode
        detector would write."""
        marker = tmp_path / "_broken_condor.json"
        marker.write_text(json.dumps({
            "ts": "2026-09-29T14:00:00+05:00",
            "strategy": "iron_condor_nifty",
            "underlying": "NIFTY",
            "expected_legs": 4,
            "placed_legs": 2,
            "filled_legs": [
                {"symbol": "NIFTY01OCT2622950CE", "side": "BUY", "qty": 75, "fill_price": 4.15}
            ],
            "reason": "SELL legs rejected",
            "consumed": False,
        }))
        with open(marker, "r") as f:
            data = json.load(f)
        assert data["strategy"] == "iron_condor_nifty"
        assert data["expected_legs"] == 4
        assert data["placed_legs"] == 2
        assert len(data["filled_legs"]) == 1
        assert data["filled_legs"][0]["side"] == "BUY"


class TestPhase4RemovalIsParseSafe:
    """Sanity check: removing the broken-condor code didn't break __main__.py."""

    def test_main_module_imports_clean(self):
        """kotak_bot.__main__ must still parse cleanly."""
        import ast
        main_py = (ROOT / "kotak_bot" / "__main__.py").read_text(encoding="utf-8")
        try:
            ast.parse(main_py)
        except SyntaxError as e:
            pytest.fail(f"__main__.py has syntax error after Phase 4: {e}")

    def test_no_orphan_local_variable_references(self):
        """Verify no dangling references to removed locals (_bc_top, _bc, _broken_*, etc.)"""
        main_py = (ROOT / "kotak_bot" / "__main__.py").read_text(encoding="utf-8")
        # These variables were local to the removed blocks. After Phase 4
        # they should not be referenced anywhere.
        for var in ["_bc_top_path", "_bc_top_filled", "_bc_top_strategy", "_bc_path",
                    "_broken_path", "_broken_state"]:
            # Count occurrences (some are in import-time references like
            # _broken_condor.json literal — but those are also gone)
            count = main_py.count(var)
            assert count == 0, (
                f"Removed local variable {var!r} still referenced {count} times after Phase 4"
            )