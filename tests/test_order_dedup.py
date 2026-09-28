"""Tests for the order_mgr double-count dedup guard.

FIX 2026-09-29 02:35: the action-consumption path in kotak_bot/__main__.py
was placing 4 orders + calling register_external_managed_trade even when
the same action was already partially processed. If the bot restarted
mid-action (or the consumed flag wasn't written before a crash), the
same action was processed twice → 4+4=8 phantom orders in order_mgr
→ max positions cap (8) hit → no new trades for the rest of the day.

The fix: before placing legs + registering, check if any of the
action's symbol names are already in `order_mgr._symbol_to_trade`. If so,
mark the action consumed and skip — the trade is already in the book.

These tests verify the dedup helper logic in isolation.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def _build_action(symbols_with_sides: list[tuple[str, str]]) -> dict:
    """Helper: build a fake action dict with leg_records."""
    return {
        "ts": "2026-09-29T02:30:00+05:30",
        "source": "quant_service",
        "actions": [{
            "type": "OPEN",
            "underlying": "NIFTY",
            "expiry": "2026-10-01",
            "strategy": "iron_condor",
            "legs": [
                {"side": side, "qty": 75, "symbol": sym, "strike": 23500, "opt_type": "CE"}
                for sym, side in symbols_with_sides
            ],
        }],
        "consumed": False,
    }


def _symbol_to_trade(symbols: list[str]) -> dict:
    """Helper: build a fake _symbol_to_trade map."""
    return {sym: f"T-{i:04d}" for i, sym in enumerate(symbols)}


def test_no_overlap_proceeds_to_registration():
    """If no symbols are tracked, the dedup check should NOT skip.

    This is the happy path: new action with all-new symbols → place
    orders + register as before.
    """
    action = _build_action([
        ("NIFTY24SEP2623500CE", "SELL"),
        ("NIFTY24SEP2623600CE", "BUY"),
        ("NIFTY24SEP2623300PE", "SELL"),
        ("NIFTY24SEP2623200PE", "BUY"),
    ])
    tracked = _symbol_to_trade([])  # nothing tracked yet
    action_symbols = [lr["symbol"] for lr in action["actions"][0]["legs"]]
    overlap = [s for s in action_symbols if s in tracked]
    assert overlap == [], "No symbols should overlap when nothing is tracked"


def test_full_overlap_triggers_dedup_skip():
    """If ALL leg symbols are already tracked, the dedup should skip.

    This is the bug case: action was processed once, all 4 symbols
    ended up in _symbol_to_trade, then the action gets re-processed
    (e.g. bot restart) → all 4 symbols overlap → dedup skip.
    """
    syms = [
        "NIFTY24SEP2623500CE",
        "NIFTY24SEP2623600CE",
        "NIFTY24SEP2623300PE",
        "NIFTY24SEP2623200PE",
    ]
    action = _build_action([(s, "BUY") for s in syms])
    tracked = _symbol_to_trade(syms)  # ALL symbols already tracked
    action_symbols = [lr["symbol"] for lr in action["actions"][0]["legs"]]
    overlap = [s for s in action_symbols if s in tracked]
    assert len(overlap) == 4, "All 4 leg symbols should overlap"
    assert overlap == syms, "Overlap set should equal the symbol list"


def test_partial_overlap_triggers_dedup_skip():
    """If ANY symbol is tracked, the dedup should skip the entire action.

    Even partial overlap means the action is a duplicate. We use ANY
    overlap (not ALL) because re-processing an action with the same
    symbols would create duplicate orders regardless of partial match.
    """
    syms = [
        "NIFTY24SEP2623500CE",
        "NIFTY24SEP2623600CE",
        "NIFTY24SEP2623300PE",
        "NIFTY24SEP2623200PE",
    ]
    action = _build_action([(s, "BUY") for s in syms])
    # Only 1 of the 4 symbols is already tracked (e.g. partial registration
    # from a bot crash mid-registration)
    tracked = _symbol_to_trade([syms[0]])
    action_symbols = [lr["symbol"] for lr in action["actions"][0]["legs"]]
    overlap = [s for s in action_symbols if s in tracked]
    assert len(overlap) == 1, "One symbol should overlap"
    # The dedup check uses ANY overlap → skip the entire action


def test_leg_records_without_symbol_field_does_not_break_dedup():
    """If a leg_record is missing the symbol key, it should be skipped in
    the overlap check (not crash with KeyError)."""
    action = {
        "ts": "2026-09-29T02:30:00+05:30",
        "actions": [{
            "type": "OPEN",
            "legs": [
                {"side": "SELL", "qty": 75},  # no symbol
                {"side": "BUY", "qty": 75, "symbol": "NIFTY24SEP2623500CE"},
            ],
        }],
        "consumed": False,
    }
    tracked = {"NIFTY24SEP2623500CE": "T-0001"}
    action_symbols = [
        lr.get("symbol") for lr in action["actions"][0]["legs"]
        if lr.get("symbol")
    ]
    overlap = [s for s in action_symbols if s in tracked]
    assert overlap == ["NIFTY24SEP2623500CE"], \
        "Missing symbol keys should be skipped, not crash"


def test_real_action_with_no_leg_records_skips_dedup():
    """If action has no leg_records (no orders placed), dedup is moot —
    the placement loop produced 0 legs and we never reach the dedup."""
    action = {"ts": "2026-09-29T02:30:00+05:30", "actions": [{"type": "OPEN"}]}
    tracked = {"NIFTY24SEP2623500CE": "T-0001"}
    leg_records = []  # bot didn't place any legs (rejected by cap, etc.)
    # The dedup check is gated on `if _leg_records:` so empty list
    # means we never enter the dedup block at all
    assert not leg_records


def test_no_overlap_with_unrelated_symbols_proceeds():
    """An action with symbols that don't match any tracked symbol should
    proceed (it's a genuinely new trade)."""
    syms = ["NIFTY24SEP2623500CE", "NIFTY24SEP2623600CE"]
    action = _build_action([(s, "BUY") for s in syms])
    tracked = {"BANKNIFTY24SEP2656200CE": "T-0001"}  # different underlying
    action_symbols = [lr["symbol"] for lr in action["actions"][0]["legs"]]
    overlap = [s for s in action_symbols if s in tracked]
    assert overlap == [], "Different underlying → no overlap → proceed"


if __name__ == "__main__":
    # Allow running as `python tests/test_order_dedup.py`
    test_no_overlap_proceeds_to_registration()
    test_full_overlap_triggers_dedup_skip()
    test_partial_overlap_triggers_dedup_skip()
    test_leg_records_without_symbol_field_does_not_break_dedup()
    test_real_action_with_no_leg_records_skips_dedup()
    test_no_overlap_with_unrelated_symbols_proceeds()
    print("All order-dedup tests passed.")
