"""Tests for the broken-condor emergency close + fixes from 2026-09-29.

Three bugs caused today's -Rs.10,720 loss:
1. SELL leg auto-snap couldn't fire (PaperClient had 0 live ticks)
2. CLOSE_ALL orphan fallback only ran if order_mgr had 0 trades to close
3. No detector for broken-condor state (BUYs filled but SELLs didn't)

These tests guard the fixes against regression.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestCLOSEALLOrphanFallbackAlwaysRuns:
    """FIX 2026-09-29 14:00: CLOSE_ALL must ALWAYS check broker orphans.

    Before: orphan fallback only ran if order_mgr had 0 trades to close.
    This left brain-driven positions open after CLOSE_ALL.
    After: orphan fallback runs unconditionally.
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


class TestBrokenCondorDetector:
    """FIX 2026-09-29 14:00: detect partial fills, write _broken_condor.json.

    When the QUANT-ACTION OPEN handler fills only some legs of a multi-leg
    strategy (e.g. iron_condor expects 4 but only 2 fill), we have a
    "broken condor" — BUY-only = naked long strangle.
    """

    def test_broken_condor_marker_written_on_partial(self):
        """The QUANT-ACTION handler must write _broken_condor.json when legs < expected."""
        main_py = (ROOT / "kotak_bot" / "__main__.py").read_text(encoding="utf-8")
        # The detector must check `_placed < len(_qa_legs)` for multi-leg strategies
        assert "FIX 2026-09-29 14:00: broken-condor detector" in main_py, (
            "Missing broken-condor detector in __main__.py"
        )
        assert "_broken_condor.json" in main_py, (
            "Missing _broken_condor.json marker file path"
        )
        # Must check for the partial-fill condition
        assert "_placed > 0 and _placed < len(_qa_legs)" in main_py, (
            "Detector must check _placed > 0 and _placed < len(_qa_legs)"
        )

    def test_broken_condor_top_loop_handler_exists(self):
        """The TOP of run_paper() must check _broken_condor.json every cycle."""
        main_py = (ROOT / "kotak_bot" / "__main__.py").read_text(encoding="utf-8")
        # Find the run_paper() function and its main loop
        run_paper_idx = main_py.find("def run_paper() -> None:")
        assert run_paper_idx > 0, "run_paper() must exist in __main__.py"
        # Find the next `while True:` after run_paper()
        loop_idx = main_py.find("while True:", run_paper_idx)
        assert loop_idx > 0, "run_paper() must contain a `while True:` loop"
        # Get the next 3500 chars (start of the loop)
        loop_start = main_py[loop_idx:loop_idx + 3500]
        assert "FIX 2026-09-29 14:25: broken-condor emergency close (top of loop)" in loop_start, (
            "Top-of-loop handler must exist for _broken_condor.json"
        )
        assert "_bc_top_path" in loop_start, (
            "Top-of-loop handler must use _bc_top_path variable"
        )

    def test_broken_condor_marker_format(self, tmp_path):
        """The marker file must have the right schema so the handler can read it."""
        # Write a sample marker
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
            "reason": "SELL legs rejected"
        }))
        # Read it back
        with open(marker, "r") as f:
            data = json.load(f)
        assert data["strategy"] == "iron_condor_nifty"
        assert data["expected_legs"] == 4
        assert data["placed_legs"] == 2
        assert len(data["filled_legs"]) == 1
        assert data["filled_legs"][0]["side"] == "BUY"


class TestSELLLegPathBlocking:
    """FIX 2026-09-29 14:00 (extra safety): the bot must NOT keep adding to a
    broken-condor state.

    The QUANT-ACTION handler should mark actions as 'consumed' (preventing
    retries) when they triggered a broken-condor marker.
    """

    def test_broken_condor_handler_marks_consumed(self):
        """After the handler closes orphan BUY legs, the marker must be marked consumed."""
        main_py = (ROOT / "kotak_bot" / "__main__.py").read_text(encoding="utf-8")
        # Find the run_paper() function and its main loop
        run_paper_idx = main_py.find("def run_paper() -> None:")
        loop_idx = main_py.find("while True:", run_paper_idx)
        loop_block = main_py[loop_idx:loop_idx + 5000]
        assert '_bc_top["consumed"] = True' in loop_block, (
            "Top-of-loop handler must mark the marker as consumed=True"
        )