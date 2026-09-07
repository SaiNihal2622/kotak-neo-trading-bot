"""Regression test for _reconstruct_today_journal.py.

Verifies that the script correctly:
  1. Pairs today's OPEN and CLOSE orders by symbol/opposite-side/FIFO
  2. Computes per-leg realized P&L with the right sign convention
  3. Writes journal entries with consistent trade_ids (idempotent re-runs)
  4. Updates performance/daily.json with the day's aggregate

The fixture mirrors today's (2026-09-07) 8 orders:
  - BNF bear-put spread: BUY 57200 PE @ 392.55, SELL 56800 PE @ 245.64,
    closed via orphan-auto-close at Rs.1.00 each (the fake-fill bug)
  - NIFTY bear-put spread: BUY 24300 PE @ 548.59, SELL 24100 PE @ 307.58,
    partial close via orphan-auto-close at Rs.1.00 (NIFTY 24100 PE)
    and force-square at 525.89 (NIFTY 24300 PE)

Expected per-leg P&L:
  BNF 57200 PE (long, closed SELL @ 1.00):  (1.00 - 392.55) * 30 = -11,746.50
  BNF 56800 PE (short, closed BUY @ 1.00):  (245.64 - 1.00) * 30 = +7,339.20
  NIFTY 24100 PE (short, closed BUY @ 1.00): (307.58 - 1.00) * 75 = +22,993.50
  NIFTY 24300 PE (long, closed SELL @ 525.89): (525.89 - 548.59) * 75 = -1,702.50
  Total: +16,883.70
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_orders():
    """Return a list of order dicts mirroring today's 8 orders."""
    today = datetime.now().strftime("%Y-%m-%d")
    base = f"{today}T"
    return [
        # BNF bear-put spread OPEN
        {"order_id": "PAPER-A0B54233CD", "symbol": "BANKNIFTY10SEP2657200PE",
         "side": "BUY", "qty": 30, "filled_qty": 30, "avg_fill_price": 392.55,
         "order_type": "MARKET", "product": "MIS", "price": 0.0,
         "tag": "QUANT-bear_put_v", "status": "complete", "exchange": "NFO",
         "strike": 57200, "option_type": "PE", "expiry": "2026-09-10",
         "underlying": "BANKNIFTY", "expected_fill_price": 392.35,
         "placed_at": f"{base}04:01:47.370684+00:00",
         "filled_at": f"{base}04:01:47.370684+00:00"},
        {"order_id": "PAPER-A1E3C84808", "symbol": "BANKNIFTY10SEP2656800PE",
         "side": "SELL", "qty": 30, "filled_qty": 30, "avg_fill_price": 245.64,
         "order_type": "MARKET", "product": "MIS", "price": 0.0,
         "tag": "QUANT-bear_put_v", "status": "complete", "exchange": "NFO",
         "strike": 56800, "option_type": "PE", "expiry": "2026-09-10",
         "underlying": "BANKNIFTY", "expected_fill_price": 245.76,
         "placed_at": f"{base}04:01:47.374683+00:00",
         "filled_at": f"{base}04:01:47.374683+00:00"},
        # BNF orphan-auto-close at Rs.1.00 (the bug)
        {"order_id": "PAPER-1E1327AF67", "symbol": "BANKNIFTY10SEP2657200PE",
         "side": "SELL", "qty": 30, "filled_qty": 30, "avg_fill_price": 1.0,
         "order_type": "MARKET", "product": "MIS", "price": 0.0,
         "tag": "ORPHAN-AUTO-CLOSE", "status": "complete", "exchange": "NFO",
         "strike": 0.0, "option_type": None, "expiry": None,
         "underlying": None, "expected_fill_price": 1.0,
         "placed_at": f"{base}06:34:54.793078+00:00",
         "filled_at": f"{base}06:34:54.793078+00:00"},
        {"order_id": "PAPER-3C4D2F5A6A", "symbol": "BANKNIFTY10SEP2656800PE",
         "side": "BUY", "qty": 30, "filled_qty": 30, "avg_fill_price": 1.0,
         "order_type": "MARKET", "product": "MIS", "price": 0.0,
         "tag": "ORPHAN-AUTO-CLOSE", "status": "complete", "exchange": "NFO",
         "strike": 0.0, "option_type": None, "expiry": None,
         "underlying": None, "expected_fill_price": 1.0,
         "placed_at": f"{base}06:34:55.862135+00:00",
         "filled_at": f"{base}06:34:55.862135+00:00"},
        # NIFTY bear-put spread OPEN
        {"order_id": "PAPER-9513535BBE", "symbol": "NIFTY10SEP2624300PE",
         "side": "BUY", "qty": 75, "filled_qty": 75, "avg_fill_price": 548.59,
         "order_type": "MARKET", "product": "MIS", "price": 0.0,
         "tag": "QUANT-bear_put_v", "status": "complete", "exchange": "NFO",
         "strike": 24300, "option_type": "PE", "expiry": "2026-09-10",
         "underlying": "NIFTY", "expected_fill_price": 548.32,
         "placed_at": f"{base}07:11:46.333838+00:00",
         "filled_at": f"{base}07:11:46.333838+00:00"},
        {"order_id": "PAPER-E1BB84C065", "symbol": "NIFTY10SEP2624100PE",
         "side": "SELL", "qty": 75, "filled_qty": 75, "avg_fill_price": 307.58,
         "order_type": "MARKET", "product": "MIS", "price": 0.0,
         "tag": "QUANT-bear_put_v", "status": "complete", "exchange": "NFO",
         "strike": 24100, "option_type": "PE", "expiry": "2026-09-10",
         "underlying": "NIFTY", "expected_fill_price": 307.73,
         "placed_at": f"{base}07:11:46.346843+00:00",
         "filled_at": f"{base}07:11:46.346843+00:00"},
        # NIFTY 24100 PE orphan-auto-close at Rs.1.00 (the bug)
        {"order_id": "PAPER-90B3F52A22", "symbol": "NIFTY10SEP2624100PE",
         "side": "BUY", "qty": 75, "filled_qty": 75, "avg_fill_price": 1.0,
         "order_type": "MARKET", "product": "MIS", "price": 0.0,
         "tag": "ORPHAN-AUTO-CLOSE", "status": "complete", "exchange": "NFO",
         "strike": 0.0, "option_type": None, "expiry": None,
         "underlying": None, "expected_fill_price": 1.0,
         "placed_at": f"{base}07:12:14.633603+00:00",
         "filled_at": f"{base}07:12:14.633603+00:00"},
        # NIFTY 24300 PE force-square at real price
        {"order_id": "PAPER-E53ED222DA", "symbol": "NIFTY10SEP2624300PE",
         "side": "SELL", "qty": 75, "filled_qty": 75, "avg_fill_price": 525.89,
         "order_type": "MARKET", "product": "MIS", "price": 0.0,
         "tag": "FORCE-SQUARE-ORPHAN", "status": "complete", "exchange": "NFO",
         "strike": 24300.0, "option_type": "PE", "expiry": "2026-09-10",
         "underlying": "NIFTY", "expected_fill_price": 526.15,
         "placed_at": f"{base}09:00:00.496462+00:00",
         "filled_at": f"{base}09:00:00.496462+00:00"},
    ]


def test_reconstruct_pairs_opens_with_closes(tmp_path, monkeypatch):
    """Verify the FIFO matching and P&L calculation against the 2026-09-07 fixture."""
    dcache = tmp_path / "data_cache"
    dcache.mkdir()
    today = datetime.now().strftime("%Y-%m-%d")
    paper_state = {
        "cash": 100000.0,
        "realized_pnl": 0.0,  # start clean
        "orders": {o["order_id"]: o for o in _make_orders()},
        "positions": {},
    }
    (dcache / "paper_state.json").write_text(json.dumps(paper_state), encoding="utf-8")

    # Patch paths inside the script
    monkeypatch.chdir(tmp_path)
    import scripts._reconstruct_today_journal as mod
    monkeypatch.setattr(mod, "PAPER_STATE_PATH", dcache / "paper_state.json")
    monkeypatch.setattr(mod, "JOURNAL_PATH", dcache / "trade_journal.jsonl")
    monkeypatch.setattr(mod, "PERF_PATH", dcache / "performance" / "daily.json")
    # Also patch ROOT so _append_to_journal writes to tmp dir
    monkeypatch.setattr(mod, "DCACHE", dcache)

    entries, summary = mod._reconstruct_today(today)
    assert len(entries) == 4, f"expected 4 matched pairs, got {len(entries)}"

    # Per-leg P&L expectations
    pnls = {e["symbol"]: e["realized_pnl"] for e in entries}
    assert abs(pnls["BANKNIFTY10SEP2657200PE"] - (-11746.50)) < 0.01, pnls
    assert abs(pnls["BANKNIFTY10SEP2656800PE"] - 7339.20) < 0.01, pnls
    assert abs(pnls["NIFTY10SEP2624100PE"] - 22993.50) < 0.01, pnls
    assert abs(pnls["NIFTY10SEP2624300PE"] - (-1702.50)) < 0.01, pnls

    # Aggregate
    assert abs(summary["realized_pnl"] - 16883.70) < 0.01
    assert summary["n_wins"] == 2
    assert summary["n_losses"] == 2
    assert summary["win_rate"] == 0.5
    # Strategy aggregation
    assert "bear_put_v" in summary["strategies"]
    assert summary["strategies"]["bear_put_v"]["count"] == 4
    assert abs(summary["strategies"]["bear_put_v"]["pnl"] - 16883.70) < 0.01
    # FIX 2026-09-07 23:15: suspect_price marking. 3 of 4 closes used the Rs.1.00
    # fallback (the orphan-auto-close bug). The 4th close (NIFTY 24300 PE) used
    # the real chain price. So 3 entries should be suspect, 1 not.
    suspect_flags = {e["symbol"]: e["suspect_price"] for e in entries}
    assert suspect_flags["BANKNIFTY10SEP2657200PE"] is True
    assert suspect_flags["BANKNIFTY10SEP2656800PE"] is True
    assert suspect_flags["NIFTY10SEP2624100PE"] is True
    assert suspect_flags["NIFTY10SEP2624300PE"] is False  # FORCE-SQUARE-ORPHAN, real price
    # suspect totals
    assert summary["suspect_count"] == 3
    suspect_pnl_sum = sum(e["realized_pnl"] for e in entries if e["suspect_price"])
    assert abs(summary["suspect_pnl"] - suspect_pnl_sum) < 0.01
    # honest_pnl = total - suspect
    expected_honest = summary["realized_pnl"] - summary["suspect_pnl"]
    assert abs(summary["honest_pnl_estimate"] - expected_honest) < 0.01
    # The only honest leg is NIFTY 24300 PE = -1702.50
    assert abs(summary["honest_pnl_estimate"] - (-1702.50)) < 0.01


def test_reconstruct_idempotent(tmp_path, monkeypatch):
    """Running the script twice should not double-write journal entries."""
    dcache = tmp_path / "data_cache"
    dcache.mkdir()
    today = datetime.now().strftime("%Y-%m-%d")
    paper_state = {
        "cash": 100000.0,
        "realized_pnl": 0.0,
        "orders": {o["order_id"]: o for o in _make_orders()},
        "positions": {},
    }
    (dcache / "paper_state.json").write_text(json.dumps(paper_state), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    import scripts._reconstruct_today_journal as mod
    monkeypatch.setattr(mod, "PAPER_STATE_PATH", dcache / "paper_state.json")
    monkeypatch.setattr(mod, "JOURNAL_PATH", dcache / "trade_journal.jsonl")
    monkeypatch.setattr(mod, "PERF_PATH", dcache / "performance" / "daily.json")
    monkeypatch.setattr(mod, "DCACHE", dcache)

    entries, _ = mod._reconstruct_today(today)
    n1 = mod._append_to_journal(entries)
    n2 = mod._append_to_journal(entries)
    assert n1 == 4
    assert n2 == 0  # already present, skip

    # Verify journal has 4 unique lines
    lines = (dcache / "trade_journal.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    ids = [json.loads(l)["trade_id"] for l in lines]
    assert len(set(ids)) == 4  # all unique


def test_reconstruct_daily_json_update(tmp_path, monkeypatch):
    """Verify performance/daily.json is updated with today's aggregate."""
    dcache = tmp_path / "data_cache"
    (dcache / "performance").mkdir(parents=True)
    today = datetime.now().strftime("%Y-%m-%d")
    paper_state = {
        "cash": 100000.0,
        "realized_pnl": 0.0,
        "orders": {o["order_id"]: o for o in _make_orders()},
        "positions": {},
    }
    (dcache / "paper_state.json").write_text(json.dumps(paper_state), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    import scripts._reconstruct_today_journal as mod
    monkeypatch.setattr(mod, "PAPER_STATE_PATH", dcache / "paper_state.json")
    monkeypatch.setattr(mod, "JOURNAL_PATH", dcache / "trade_journal.jsonl")
    monkeypatch.setattr(mod, "PERF_PATH", dcache / "performance" / "daily.json")
    monkeypatch.setattr(mod, "DCACHE", dcache)

    entries, summary = mod._reconstruct_today(today)
    mod._append_to_journal(entries)
    mod._update_daily_json(summary, today)

    daily = json.loads((dcache / "performance" / "daily.json").read_text(encoding="utf-8"))
    assert daily["date"] == today
    assert daily["trades"] == 4
    assert daily["realized_pnl"] == pytest.approx(16883.70, abs=0.01)
    assert "bear_put_v" in daily["strategies"]
    # FIX 2026-09-07 23:15: data quality fields
    assert daily["suspect_fill_count"] == 3
    assert daily["data_quality"] == "partial_fake"
    assert daily["honest_pnl_estimate"] == pytest.approx(-1702.50, abs=0.01)


def test_reconstruct_handles_no_today_orders(tmp_path, monkeypatch):
    """If no orders match today's date, return empty list."""
    dcache = tmp_path / "data_cache"
    dcache.mkdir()
    today = datetime.now().strftime("%Y-%m-%d")
    # Paper state with only yesterday's orders
    yesterday = "2026-09-01"
    paper_state = {
        "cash": 100000.0,
        "realized_pnl": 0.0,
        "orders": {
            "PAPER-OLD1": {
                "order_id": "PAPER-OLD1", "symbol": "NIFTY10SEP2624300PE",
                "side": "BUY", "qty": 75, "filled_qty": 75, "avg_fill_price": 100.0,
                "tag": "QUANT-test", "status": "complete", "exchange": "NFO",
                "placed_at": f"{yesterday}T04:01:47.370684+00:00",
                "filled_at": f"{yesterday}T04:01:47.370684+00:00",
            }
        },
        "positions": {},
    }
    (dcache / "paper_state.json").write_text(json.dumps(paper_state), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    import scripts._reconstruct_today_journal as mod
    monkeypatch.setattr(mod, "PAPER_STATE_PATH", dcache / "paper_state.json")
    monkeypatch.setattr(mod, "JOURNAL_PATH", dcache / "trade_journal.jsonl")
    monkeypatch.setattr(mod, "PERF_PATH", dcache / "performance" / "daily.json")
    monkeypatch.setattr(mod, "DCACHE", dcache)

    entries, summary = mod._reconstruct_today(today)
    assert entries == []
    assert summary["n_trades"] == 0
    assert summary["realized_pnl"] == 0
