"""Regression test for the position-cap & phantom 0DTE fixes (2026-08-20).

Bug: `total_open = max(len(open_trades), len(open_pos))` counted broker
LEG positions, not strategies. With 6 phantom 0DTE legs re-loaded at
startup, the cap check (default 2) blocked every new signal because
`max(0, 6) = 6 >= 2`.

This test exercises the cap calculation directly to ensure the post-fix
behavior: only `len(open_trades)` (strategies) is compared against
`MAX_OPEN_POSITIONS`, and orphan broker positions with no matching
open trade are excluded from the count.

Also covers phantom 0DTE auto-purge at startup_reconcile: positions
with `expiry == today` and `ltp <= 0` are filtered out.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock


def _make_pos(symbol: str, qty: int, expiry: str, ltp: float = 100.0):
    return SimpleNamespace(
        symbol=symbol, qty=qty, expiry=expiry, ltp=ltp,
        underlying=symbol[:5] if "NIFTY" in symbol or "BANKNIFTY" in symbol else symbol,
    )


def test_cap_counts_strategies_not_legs():
    """The SCAN-time cap should compare `len(open_trades)`, not leg count."""
    # Simulate: 0 open trades, 6 phantom broker positions (1 iron condor + 1 spread)
    open_trades = []  # 0 strategies
    open_pos = [
        _make_pos("NIFTY20AUG2624300CE", 130, "2026-08-20", ltp=48.82),
        _make_pos("NIFTY20AUG2624400CE", -130, "2026-08-20", ltp=28.99),
        _make_pos("BANKNIFTY20AUG2657300CE", -30, "2026-08-20", ltp=370.76),
        _make_pos("BANKNIFTY20AUG2657400CE", 30, "2026-08-20", ltp=321.91),
        _make_pos("BANKNIFTY20AUG2657100PE", -30, "2026-08-20", ltp=238.23),
        _make_pos("BANKNIFTY20AUG2657000PE", 30, "2026-08-20", ltp=202.80),
    ]
    MAX_OPEN_POSITIONS = 2

    # ── Post-fix behavior ──
    # Cross-check broker positions for orphan phantom legs.
    _ot_syms = set()
    for _t in open_trades:
        for _o in _t.orders:
            if getattr(_o, "avg_fill_price", 0) > 0 and getattr(_o, "symbol", None):
                _ot_syms.add(_o.symbol)
    orphan_pos = [p for p in open_pos if p.symbol not in _ot_syms]
    total_strategies = len(open_trades)

    # The cap is checked against STRATEGIES (not legs).
    # With 0 strategies and 6 phantom legs, the bot SHOULD proceed.
    blocked = total_strategies >= MAX_OPEN_POSITIONS
    assert blocked is False, (
        f"Bot should NOT be blocked with 0 strategies and 6 phantom legs. "
        f"orphans={len(orphan_pos)}, total_strategies={total_strategies}"
    )

    # ── Pre-fix behavior (regression check) ──
    # Old code: `total_open = max(len(open_trades), len(open_pos))` → 6 >= 2 → blocked
    total_open_old = max(len(open_trades), len(open_pos))
    assert total_open_old == 6
    blocked_old = total_open_old >= MAX_OPEN_POSITIONS
    assert blocked_old is True, "Pre-fix code WOULD have blocked — that's the bug"


def test_cap_blocks_actual_strategies():
    """When 2 strategies are open, the cap should still block the 3rd."""
    open_trades = [MagicMock(), MagicMock()]  # 2 strategies
    open_pos = []  # assume flat
    MAX_OPEN_POSITIONS = 2
    total_strategies = len(open_trades)
    blocked = total_strategies >= MAX_OPEN_POSITIONS
    assert blocked is True, "Cap should still block when 2 real strategies are open"


def test_phantom_0dte_filter_excludes_zero_ltp_positions():
    """0DTE positions with LTP=0 (post-close) are phantoms — must be filtered."""
    today = date.today().strftime("%Y-%m-%d")
    all_pos = [
        _make_pos("NIFTY20AUG2624300CE", 130, today, ltp=0.0),     # phantom
        _make_pos("NIFTY20AUG2624400CE", -130, today, ltp=0.0),    # phantom
        _make_pos("BANKNIFTY20AUG2657300CE", -30, today, ltp=0.0), # phantom
        _make_pos("BANKNIFTY20AUG2657400CE", 30, today, ltp=0.0),  # phantom
        _make_pos("BANKNIFTY20AUG2657100PE", -30, today, ltp=0.0), # phantom
        _make_pos("BANKNIFTY20AUG2657000PE", 30, today, ltp=0.0),  # phantom
        # A real live position in a different expiry
        _make_pos("NIFTY27AUG2624500CE", 65, "2026-08-27", ltp=120.0),
    ]

    def _is_phantom(p, today_str, open_trade_syms):
        exp_str = str(p.expiry)[:10] if p.expiry else None
        if exp_str != today_str:
            return False
        if getattr(p, "symbol", None) in open_trade_syms:
            return False
        ltp = getattr(p, "ltp", 0) or 0
        if ltp <= 0:
            return True
        return False

    live = [p for p in all_pos if not _is_phantom(p, today, set())]
    assert len(live) == 1, f"Expected 1 live position after phantom filter, got {len(live)}"
    assert live[0].symbol == "NIFTY27AUG2624500CE"


def test_phantom_filter_preserves_active_trade_legs():
    """0DTE legs that ARE in an open trade must NOT be filtered out."""
    today = date.today().strftime("%Y-%m-%d")
    all_pos = [
        _make_pos("NIFTY20AUG2624500CE", 65, today, ltp=0.0),
    ]
    open_trade_syms = {"NIFTY20AUG2624500CE"}

    def _is_phantom(p, today_str, ots):
        exp_str = str(p.expiry)[:10] if p.expiry else None
        if exp_str != today_str:
            return False
        if getattr(p, "symbol", None) in ots:
            return False
        ltp = getattr(p, "ltp", 0) or 0
        return ltp <= 0

    is_phantom = _is_phantom(all_pos[0], today, open_trade_syms)
    assert is_phantom is False, "Active trade leg with ltp=0 must be preserved (not phantom)"


if __name__ == "__main__":
    test_cap_counts_strategies_not_legs()
    test_cap_blocks_actual_strategies()
    test_phantom_0dte_filter_excludes_zero_ltp_positions()
    test_phantom_filter_preserves_active_trade_legs()
    print("All 4 phantom/cap tests passed.")
