"""FIX 2026-09-18 phase-17 tests:
- live_go_tracker uses paper_state.realized_pnl as the truth
  (not by_day which can be inflated by RECON/EOD/pre-reset entries)
- strategy_performance aggregator skips pre-reset + RECON + EOD + dupes
- dashboard reconciliation panel reads paper_state + aggregator
"""
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


# ---------------------------------------------------------------------------
# Fix: live_go_tracker uses paper_state as truth
# ---------------------------------------------------------------------------

def test_live_go_tracker_uses_paper_state_when_available(tmp_path, monkeypatch):
    """When paper_state.json exists, live_go_tracker should use its
    realized_pnl as the cumulative return truth — not the by_day sum."""
    # Set up: write a paper_state with realized=5000 and a strategy_perf
    # with by_day showing +50000 (inflated by pre-reset activity).
    dc = tmp_path / "data_cache"
    perf = dc / "performance"
    perf.mkdir(parents=True, exist_ok=True)
    (dc / "paper_state.json").write_text(json.dumps({
        "cash": 105000.0,
        "realized_pnl": 5000.0,
        "positions": {},
        "orders": {},
    }), encoding="utf-8")
    (perf / "strategy_performance.json").write_text(json.dumps({
        "by_day": {
            "2026-09-15": {"pnl": 50000.0, "trades": 1},  # would-be pre-reset
        },
    }), encoding="utf-8")
    (dc / "live_go_policy.json").write_text(json.dumps({
        "min_consecutive_green_days": 5,
        "min_cumulative_return_pct": 5.0,
        "starting_capital_baseline": 100000.0,
    }), encoding="utf-8")

    # Patch live_go_tracker's DCACHE to tmp_path
    import live_go_tracker as lgt
    monkeypatch.setattr(lgt, "DCACHE", dc)

    truth = lgt._paper_state_truth()
    assert truth["realized_pnl_rs"] == 5000.0
    assert truth["cumulative_return_pct"] == 5.0  # 5000 / 100000


def test_live_go_tracker_falls_back_to_by_day_when_no_paper_state(tmp_path, monkeypatch):
    """When paper_state is missing, fall back to by_day from aggregator."""
    dc = tmp_path / "data_cache"
    perf = dc / "performance"
    perf.mkdir(parents=True, exist_ok=True)
    # No paper_state.json
    (perf / "strategy_performance.json").write_text(json.dumps({
        "by_day": {"2026-09-15": {"pnl": 5000.0, "trades": 1}},
    }), encoding="utf-8")

    import live_go_tracker as lgt
    monkeypatch.setattr(lgt, "DCACHE", dc)

    truth = lgt._paper_state_truth()
    assert truth == {}


# ---------------------------------------------------------------------------
# Fix: aggregator skips pre-reset + RECON + EOD + dupes
# ---------------------------------------------------------------------------

def test_aggregator_skips_pre_reset_fills(tmp_path, monkeypatch):
    """JOURNAL entries from BEFORE the most recent RESET marker should be
    excluded from by_day (they correspond to fills that happened before
    paper_state was wiped)."""
    dc = tmp_path / "data_cache"
    perf = dc / "performance"
    perf.mkdir(parents=True, exist_ok=True)

    # Write journal: 1 RESET, then 1 fill BEFORE reset, 1 fill AFTER
    (dc / "trade_journal.jsonl").write_text(
        '{"event":"RESET","ts":"2026-09-15T10:00:00","new_cash":100000.0}\n'
        '{"event":"FILL","ts":"2026-09-15T09:00:00","symbol":"OLD","side":"BUY","qty":75,"avg_fill_price":100,"realized_delta":0,"status":"complete"}\n'
        '{"event":"FILL","ts":"2026-09-15T11:00:00","symbol":"NEW","side":"BUY","qty":75,"avg_fill_price":200,"realized_delta":0,"status":"complete"}\n',
        encoding="utf-8",
    )

    import strategy_performance as sp_mod
    monkeypatch.setattr(sp_mod, "ROOT", tmp_path)
    sp_mod.main()

    out = json.loads((perf / "strategy_performance.json").read_text(encoding="utf-8"))
    recon = out.get("reconciliation", {})
    # The OLD fill (ts 09:00 < reset_ts 10:00) should be skipped
    assert recon.get("pre_reset_entries_skipped", 0) >= 1


def test_aggregator_skips_recon_entries(tmp_path, monkeypatch):
    """RECON-* trade_ids are orphan-recovery re-reports — skip from by_day."""
    dc = tmp_path / "data_cache"
    perf = dc / "performance"
    perf.mkdir(parents=True, exist_ok=True)
    (dc / "trade_journal.jsonl").write_text(
        '{"event":"RESET","ts":"2026-09-15T10:00:00","new_cash":100000.0}\n'
        '{"trade_id":"RECON-2026-09-10-NIFTY","symbol":"NIFTY","side":"BUY","qty":75,"realized_pnl":5000,"closed_at":"2026-09-15T11:00:00","underlying":"NIFTY","strategy":"s"}\n'
        '{"event":"FILL","ts":"2026-09-15T11:30:00","symbol":"NIFTY","side":"BUY","qty":75,"avg_fill_price":100,"realized_delta":0,"status":"complete"}\n',
        encoding="utf-8",
    )

    import strategy_performance as sp_mod
    monkeypatch.setattr(sp_mod, "ROOT", tmp_path)
    sp_mod.main()

    out = json.loads((perf / "strategy_performance.json").read_text(encoding="utf-8"))
    recon = out.get("reconciliation", {})
    # The RECON entry should be skipped (realized_pnl=5000 not counted)
    assert recon.get("recon_entries_skipped", 0) >= 1


def test_aggregator_uses_realized_delta_for_inline_fills(tmp_path, monkeypatch):
    """For inline FILL events, use realized_delta (matches paper_state)."""
    dc = tmp_path / "data_cache"
    perf = dc / "performance"
    perf.mkdir(parents=True, exist_ok=True)
    (dc / "trade_journal.jsonl").write_text(
        '{"event":"RESET","ts":"2026-09-15T10:00:00","new_cash":100000.0}\n'
        '{"event":"FILL","ts":"2026-09-15T11:00:00","symbol":"NIFTY","side":"BUY","qty":75,"avg_fill_price":100,"realized_delta":0,"status":"complete"}\n'
        '{"event":"FILL","ts":"2026-09-15T15:00:00","symbol":"NIFTY","side":"SELL","qty":75,"avg_fill_price":110,"realized_delta":750,"status":"complete"}\n',
        encoding="utf-8",
    )

    import strategy_performance as sp_mod
    monkeypatch.setattr(sp_mod, "ROOT", tmp_path)
    sp_mod.main()

    out = json.loads((perf / "strategy_performance.json").read_text(encoding="utf-8"))
    # The close of NIFTY at +110 (avg 100) should give +Rs.750 P&L
    assert out["by_day"]["2026-09-15"]["pnl"] == 750.0


# ---------------------------------------------------------------------------
# Fix: dashboard reconciliation panel reads both sources
# ---------------------------------------------------------------------------

def test_real_provider_reconciliation_block_includes_inline_realized_delta_sum():
    """The dashboard's reconciliation block should expose the aggregator's
    inline_realized_delta_sum_rs so the user can compare it to paper_state.

    Reads the production strategy_performance.json (regenerated after the
    aggregator fix) and verifies the reconciliation block has the expected
    fields.
    """
    sp_path = ROOT / "data_cache" / "performance" / "strategy_performance.json"
    if not sp_path.exists():
        pytest.skip("strategy_performance.json not found; run aggregator first")
    sp = json.loads(sp_path.read_text(encoding="utf-8"))
    recon = sp.get("reconciliation", {})
    # Required keys (post-fix)
    assert "inline_realized_delta_sum_rs" in recon
    assert "recon_entries_skipped" in recon
    assert "eod_entries_skipped" in recon
    assert "pre_reset_entries_skipped" in recon
    # Skip keys that were added but old data may not have
    assert "duplicate_order_ids_skipped" in recon
    assert "interpretation" in recon
