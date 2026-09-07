"""_reconstruct_today_journal.py - reconstruct today's trade_journal.jsonl from paper_state.json.

FIX 2026-09-07 22:30: paper_client._apply_fill() does NOT call trade_journal.journal_open
or trade_journal.journal_close. The journal is only written by the EOD P&L evaluator
for OPEN positions at 15:30 IST. But the bot force-squares everything at 14:30, so by
15:30 there are no open positions and the evaluator writes nothing. The whole day's
trades are missing from trade_journal.jsonl, breaking the per-strategy P&L aggregation
in performance/strategy_performance.py and the journal-aware Telegram /strategy command.

This script:
  1. Reads paper_state.json and gets all today's filled orders
  2. Groups orders by (symbol, side) chronologically to detect OPEN/CLOSE pairs
  3. Computes per-leg realized P&L: (close_px - open_px) * qty * sign
     where sign = +1 for SELL (you sold at open_px, bought back at close_px),
     and -1 for BUY (you bought at open_px, sold at close_px)
  4. Writes one journal entry per (open, close) pair to trade_journal.jsonl
  5. Updates performance/daily.json with today's aggregate metrics

The script is idempotent for the (open, close) pair detection: each open and each
close order is matched at most once. Re-running won't double-write the same pair.

Run manually:
  python scripts/_reconstruct_today_journal.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent.resolve()
DCACHE = ROOT / "data_cache"
JOURNAL_PATH = DCACHE / "trade_journal.jsonl"
PERF_PATH = DCACHE / "performance" / "daily.json"
PAPER_STATE_PATH = DCACHE / "paper_state.json"


def _is_close_tag(tag: str) -> bool:
    """A close order has a tag like 'close_PAPER-XXX', 'ORPHAN-AUTO-CLOSE', or
    'FORCE-SQUARE-ORPHAN'. An open order has tag like 'QUANT-bear_put_v'."""
    if not tag:
        return False
    t = tag.upper()
    return t.startswith("CLOSE_") or "AUTO-CLOSE" in t or "FORCE-SQUARE" in t or "ORPHAN" in t


def _is_open_tag(tag: str) -> bool:
    """Open orders are tagged with the strategy name (e.g. 'QUANT-bear_put_v',
    'TEMPLATE-iron_condor') or 'QUANT-...'. Anything else is treated as a close
    or a system-level action."""
    if not tag:
        return False
    t = tag.upper()
    if t.startswith("CLOSE_") or "AUTO-CLOSE" in t or "FORCE-SQUARE" in t or "ORPHAN" in t:
        return False
    # Heuristic: opens have a hyphen-separated strategy name
    return bool(t.startswith("QUANT-") or t.startswith("TEMPLATE-") or t.startswith("MAVIS-"))


def _reconstruct_today(today: str) -> tuple:
    """Walk paper_state.json orders, match open/close pairs for `today`,
    return (entries, summary) where:
      - entries: list of dicts to write to trade_journal.jsonl
      - summary: dict of aggregate metrics for daily.json

    Algorithm:
      1. Filter today's filled orders.
      2. Sort by placed_at.
      3. Group by symbol. For each symbol, the orders alternate between
         opens (tag starts with QUANT-/TEMPLATE-/MAVIS-) and closes
         (tag like ORPHAN-AUTO-CLOSE / FORCE-SQUARE-ORPHAN / close_*).
      4. Pair each close with the most-recently-opened open of opposite
         side and matching qty (FIFO across the whole day, not per-bucket).
      5. Compute per-leg realized P&L:
           - If open side is BUY  (long):  realized = (close_px - open_px) * qty
           - If open side is SELL (short): realized = (open_px - close_px) * qty
    """
    if not PAPER_STATE_PATH.exists():
        print(f"paper_state.json missing at {PAPER_STATE_PATH}")
        return [], {}

    ps = json.loads(PAPER_STATE_PATH.read_text(encoding="utf-8"))
    orders = ps.get("orders", {})

    # Filter today's filled orders
    todays = []
    for oid, o in orders.items():
        placed_at = o.get("placed_at", "") or ""
        if not placed_at.startswith(today):
            continue
        if o.get("status") not in ("complete", "filled"):
            continue
        if (o.get("avg_fill_price") or 0) <= 0:
            continue
        o["_oid"] = oid
        todays.append(o)
    todays.sort(key=lambda x: x.get("placed_at", ""))

    # Bucket by symbol only (not side — opens and closes are opposite sides
    # of the same underlying contract and need to be matched together).
    by_symbol = defaultdict(list)
    for o in todays:
        by_symbol[o.get("symbol", "")].append(o)

    entries = []
    n_wins = 0
    n_losses = 0
    n_breakeven = 0
    total_pnl = 0.0
    strategies = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0, "count": 0})

    for sym, sym_orders in by_symbol.items():
        opens = [o for o in sym_orders if _is_open_tag(o.get("tag", ""))]
        closes = [o for o in sym_orders if not _is_open_tag(o.get("tag", ""))]

        used_open_ids = set()
        for c in closes:
            c_qty = c.get("filled_qty", 0) or 0
            c_px = c.get("avg_fill_price", 0) or 0
            c_time = c.get("placed_at", "")
            c_side = c.get("side", "")

            # Find the latest unused open before the close with opposite side and same qty
            matched_open = None
            for o in sorted(opens, key=lambda x: x.get("placed_at", ""), reverse=True):
                if o["_oid"] in used_open_ids:
                    continue
                if o.get("placed_at", "") >= c_time:
                    continue
                if o.get("side", "") == c_side:
                    continue
                if (o.get("filled_qty", 0) or 0) != c_qty:
                    continue
                matched_open = o
                break
            if not matched_open:
                # Stranded close — no matching open. Skip.
                continue
            used_open_ids.add(matched_open["_oid"])

            o_px = matched_open.get("avg_fill_price", 0) or 0
            o_side = matched_open.get("side", "")
            # Long (open BUY, close SELL): realized = (close_px - open_px) * qty
            # Short (open SELL, close BUY): realized = (open_px - close_px) * qty
            if o_side == "BUY":
                pnl = (c_px - o_px) * c_qty
            else:
                pnl = (o_px - c_px) * c_qty

            tag = matched_open.get("tag", "") or c.get("tag", "")
            entry = {
                "trade_id": f"RECON-{today}-{sym[:20]}-{c.get('placed_at', '?')[-9:-3]}",
                "symbol": sym,
                "underlying": matched_open.get("underlying", "") or c.get("underlying", ""),
                "strike": matched_open.get("strike", 0) or c.get("strike", 0),
                "option_type": matched_open.get("option_type", "") or c.get("option_type", ""),
                "qty": c_qty,
                "open_side": o_side,
                "avg_price": round(o_px, 2),
                "exit_ltp": round(c_px, 2),
                "realized_pnl": round(pnl, 2),
                "exit_source": c.get("tag", "reconstructed"),
                "open_tag": tag,
                "close_tag": c.get("tag", ""),
                "opened_at": matched_open.get("placed_at", ""),
                "closed_at": c.get("filled_at", "") or c.get("placed_at", ""),
                "status": "closed_reconstructed",
            }
            entries.append(entry)
            total_pnl += pnl
            if pnl > 0:
                n_wins += 1
            elif pnl < 0:
                n_losses += 1
            else:
                n_breakeven += 1
            # Group by strategy (strip the QUANT-/TEMPLATE-/MAVIS- prefix)
            for prefix in ("QUANT-", "TEMPLATE-", "MAVIS-", "quant-", "template-", "mavis-"):
                if tag.startswith(prefix):
                    tag = tag[len(prefix):]
                    break
            strategies[tag]["count"] += 1
            strategies[tag]["pnl"] += pnl
            if pnl > 0:
                strategies[tag]["wins"] += 1
            elif pnl < 0:
                strategies[tag]["losses"] += 1

    summary = {
        "date": today,
        "n_trades": len(entries),
        "n_wins": n_wins,
        "n_losses": n_losses,
        "n_breakeven": n_breakeven,
        "win_rate": n_wins / len(entries) if entries else 0,
        "realized_pnl": round(total_pnl, 2),
        "strategies": {k: dict(v) for k, v in strategies.items()},
    }
    return entries, summary


def _append_to_journal(entries: list) -> int:
    """Append entries to trade_journal.jsonl. Returns count written.
    Skips entries whose trade_id is already in the file (idempotent)."""
    existing_ids = set()
    if JOURNAL_PATH.exists():
        for line in JOURNAL_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                existing_ids.add(json.loads(line).get("trade_id"))
            except Exception:
                pass
    n_written = 0
    with JOURNAL_PATH.open("a", encoding="utf-8") as f:
        for e in entries:
            if e["trade_id"] in existing_ids:
                continue
            f.write(json.dumps(e) + "\n")
            n_written += 1
    return n_written


def _update_daily_json(summary: dict, today: str) -> None:
    """Update performance/daily.json with today's aggregate metrics."""
    PERF_PATH.parent.mkdir(parents=True, exist_ok=True)
    if PERF_PATH.exists():
        try:
            perf = json.loads(PERF_PATH.read_text(encoding="utf-8"))
        except Exception:
            perf = {}
    else:
        perf = {}
    # Top-level fields
    perf["date"] = today
    perf["trades"] = summary["n_trades"]
    perf["closed"] = summary["n_trades"]
    perf["wins"] = summary["n_wins"]
    perf["losses"] = summary["n_losses"]
    perf["breakevens"] = summary["n_breakeven"]
    perf["win_rate"] = round(summary["win_rate"], 4)
    perf["realized_pnl"] = round(summary["realized_pnl"], 2)
    avg_win = (summary["realized_pnl"] / max(summary["n_wins"], 1)) if summary["n_wins"] else 0
    avg_loss = (summary["realized_pnl"] / max(summary["n_losses"], 1)) if summary["n_losses"] else 0
    perf["avg_win"] = round(avg_win, 2)
    perf["avg_loss"] = round(avg_loss, 2)
    perf["strategies"] = summary["strategies"]
    perf["last_updated"] = datetime.now().isoformat(timespec="seconds")
    PERF_PATH.write_text(json.dumps(perf, indent=2), encoding="utf-8")


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"=== Trade journal reconstruction for {today} ===\n")

    # Pre-existing realized_pnl (carryover from prior days) — to detect
    # deltas in case the per-day reconstruction doesn't match the bot's
    # running total.
    if PAPER_STATE_PATH.exists():
        ps = json.loads(PAPER_STATE_PATH.read_text(encoding="utf-8"))
        bot_realized = float(ps.get("realized_pnl", 0) or 0)
    else:
        bot_realized = 0.0

    entries, summary = _reconstruct_today(today)
    if not entries:
        print("no filled orders to reconstruct")
        return 0

    print(f"reconstructed {len(entries)} trade-pair entries")
    n_written = _append_to_journal(entries)
    print(f"wrote {n_written} new entries to {JOURNAL_PATH.name}")
    print(f"  (skipped {len(entries) - n_written} already-present trade_ids)")
    print()
    print(f"summary: {summary['n_trades']} trades, {summary['n_wins']} wins, {summary['n_losses']} losses")
    print(f"  realized_pnl (today's trades only): Rs.{summary['realized_pnl']:,.2f}")
    print(f"  pre-existing realized_pnl (carryover): Rs.{bot_realized - summary['realized_pnl']:+,.2f}")
    print(f"  bot's running realized_pnl: Rs.{bot_realized:+,.2f}")
    print(f"  strategies:")
    for strat, m in summary["strategies"].items():
        print(f"    {strat}: {m['count']} trades, Rs.{m['pnl']:+,.2f}, {m['wins']}W / {m['losses']}L")

    _update_daily_json(summary, today)
    print(f"\nupdated {PERF_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
