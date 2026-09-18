"""FIX 2026-09-18 phase-14 regression tests:
- early-reject LIMIT @ price=0 in paper_client.place_order
- order_manager converts zero-priced LIMITs to MARKET
- state-sync drift detection in quant_service context
- phantom-fill exclusion in strategy_performance aggregator
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Fix 1: Early-reject LIMIT @ price=0 in paper_client.place_order
# ---------------------------------------------------------------------------

def test_paper_client_rejects_limit_at_price_zero():
    """A LIMIT order with price=0 must be rejected at placement, not 60s later."""
    from kotak_bot.broker.paper_client import PaperClient
    from kotak_bot.broker.base import Order, OrderSide, OrderType, ProductType

    pc = PaperClient.__new__(PaperClient)  # bypass __init__
    pc.fill_mode = "realistic"
    pc.NSE_TICK_SIZE = 0.05
    pc._lock = __import__("threading").Lock()
    pc._connected = True
    pc._orders = {}
    pc._positions = {}
    pc._ticks = {}
    pc._realized_pnl = 0.0
    pc._cash = 100000.0
    pc._order_placed_ts = {}
    pc._fill_callbacks = []
    pc._tick_callbacks = []
    pc._last_state = {}
    pc.unfilled_order_timeout_sec = 60
    pc.partial_fill_min_pct = 1.0
    pc.limit_fill_min_spread = 0.05
    pc.limit_fill_spread_pct = 0.5
    pc.limit_fill_near_ltp_pct = 0.5
    pc.slippage_bps = 5
    pc.persist_path = Path("data_cache/_test_paper.json")
    from datetime import datetime, timezone
    pc._last_save = datetime.now(timezone.utc)
    import os
    os.makedirs(pc.persist_path.parent, exist_ok=True)

    order = Order(
        symbol="NIFTY17SEP2623200CE",
        side=OrderSide.BUY,
        qty=75,
        order_type=OrderType.LIMIT,
        product=ProductType.MIS,
        price=0.0,
        strike=23200,
        option_type="CE",
        expiry="2026-09-17",
        underlying="NIFTY",
    )
    from kotak_bot.broker.base import OrderStatus
    pc.place_order(order)
    assert order.status == OrderStatus.REJECTED, f"expected REJECTED, got {order.status}"
    assert "price=0" in (order.rejection_reason or "").lower() or "must be > 0" in (order.rejection_reason or "").lower()


def test_paper_client_rejects_limit_at_price_none():
    """A LIMIT order with price=None must also be rejected."""
    from kotak_bot.broker.paper_client import PaperClient
    from kotak_bot.broker.base import Order, OrderSide, OrderType, ProductType, OrderStatus

    pc = PaperClient.__new__(PaperClient)
    pc.fill_mode = "realistic"
    pc.NSE_TICK_SIZE = 0.05
    pc._lock = __import__("threading").Lock()
    pc._connected = True
    pc._orders = {}
    pc._positions = {}
    pc._ticks = {}
    pc._realized_pnl = 0.0
    pc._cash = 100000.0
    pc._order_placed_ts = {}
    pc._fill_callbacks = []
    pc._tick_callbacks = []
    pc._last_state = {}
    pc.unfilled_order_timeout_sec = 60
    pc.partial_fill_min_pct = 1.0
    pc.limit_fill_min_spread = 0.05
    pc.limit_fill_spread_pct = 0.5
    pc.limit_fill_near_ltp_pct = 0.5
    pc.slippage_bps = 5
    pc.persist_path = Path("data_cache/_test_paper2.json")
    from datetime import datetime, timezone
    pc._last_save = datetime.now(timezone.utc)

    order = Order(
        symbol="NIFTY17SEP2623200CE",
        side=OrderSide.BUY,
        qty=75,
        order_type=OrderType.LIMIT,
        product=ProductType.MIS,
        price=None,
        strike=23200,
        option_type="CE",
        expiry="2026-09-17",
        underlying="NIFTY",
    )
    pc.place_order(order)
    assert order.status == OrderStatus.REJECTED


def test_market_order_still_works():
    """A MARKET order should not be affected by the price=0 fix.
    With the chain-as-fallback fix (Phase 15), the chain has bid/ask for
    ATM strikes, so MARKET orders fill from chain when no live tick is
    available. The important thing here is that the order is NOT rejected
    for missing price (only LIMIT @ price=0 should be rejected for that).
    """
    from kotak_bot.broker.paper_client import PaperClient
    from kotak_bot.broker.base import Order, OrderSide, OrderType, ProductType, OrderStatus

    pc = PaperClient.__new__(PaperClient)
    pc.fill_mode = "realistic"
    pc.NSE_TICK_SIZE = 0.05
    pc._lock = __import__("threading").Lock()
    pc._connected = True
    pc._orders = {}
    pc._positions = {}
    pc._ticks = {}
    pc._realized_pnl = 0.0
    pc._cash = 100000.0
    pc._order_placed_ts = {}
    pc._fill_callbacks = []
    pc._tick_callbacks = []
    pc._last_state = {}
    pc.unfilled_order_timeout_sec = 60
    pc.partial_fill_min_pct = 1.0
    pc.limit_fill_min_spread = 0.05
    pc.limit_fill_spread_pct = 0.5
    pc.limit_fill_near_ltp_pct = 0.5
    pc.slippage_bps = 5
    pc.persist_path = Path("data_cache/_test_paper3.json")
    from datetime import datetime, timezone
    pc._last_save = datetime.now(timezone.utc)

    # Use a strike that ISN'T in the production chain so we can verify
    # that without chain data, MARKET order sits OPEN (not rejected).
    order = Order(
        symbol="XYZ24SEP2623200CE",  # unknown underlying → no chain → no fill
        side=OrderSide.BUY,
        qty=75,
        order_type=OrderType.MARKET,
        product=ProductType.MIS,
        price=None,
        strike=23200,
        option_type="CE",
        expiry="2026-09-24",
        underlying="XYZ",
    )
    pc.place_order(order)
    # No chain for XYZ → no tick → MARKET order sits OPEN (waiting for tick).
    # Important: NOT rejected for missing price (that's only for LIMIT @ price=0).
    assert order.status == OrderStatus.OPEN


# ---------------------------------------------------------------------------
# Fix 4: Phantom-fill exclusion in strategy_performance aggregator
# ---------------------------------------------------------------------------

def test_strategy_performance_excludes_phantom_fills(tmp_path, monkeypatch):
    """FIX 2026-09-18 11:15: phantom_price entries must NOT contribute to
    by_day P&L. They appear in the 'phantom' metadata block instead."""
    # Set up a temp data_cache layout
    dc = tmp_path / "data_cache"
    perf = dc / "performance"
    perf.mkdir(parents=True, exist_ok=True)
    journal = dc / "trade_journal.jsonl"
    # 1 phantom fill (+1000 phantom P&L) + 1 real fill (-100 real P&L)
    journal.write_text(
        '{"trade_id":"X1","realized_pnl":1000,"closed_at":"2026-09-15T10:00:00","strategy":"s","underlying":"NIFTY","phantom_price":true}\n'
        '{"trade_id":"X2","realized_pnl":-100,"closed_at":"2026-09-15T11:00:00","strategy":"s","underlying":"NIFTY","phantom_price":false}\n',
        encoding="utf-8",
    )
    # Monkey-patch ROOT inside strategy_performance so it writes to tmp_path
    sys.path.insert(0, str(ROOT / "scripts"))
    import strategy_performance as sp_mod
    monkeypatch.setattr(sp_mod, "ROOT", tmp_path)
    sp_mod.main()
    out_path = perf / "strategy_performance.json"
    assert out_path.exists()
    out = json.loads(out_path.read_text(encoding="utf-8"))
    by_day_15 = out.get("by_day", {}).get("2026-09-15", {})
    # Phantom excluded → by_day should be -100 only, not +900
    assert by_day_15.get("pnl", 0) == -100, f"phantom not excluded; got {by_day_15}"
    assert by_day_15.get("trades", 0) == 1
    phantom_meta = out.get("phantom", {})
    assert phantom_meta.get("count") == 1, f"phantom count wrong: {phantom_meta}"
    assert phantom_meta.get("pnl_excluded_rs") == 1000, f"phantom pnl wrong: {phantom_meta}"
