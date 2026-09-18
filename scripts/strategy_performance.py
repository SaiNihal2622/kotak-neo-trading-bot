"""strategy_performance.py - per-strategy performance tracker.

FIX 2026-09-04 13:58: aggregates trade_journal.jsonl by strategy (long_put,
bull_call_vertical, iron_condor, etc.) and computes per-strategy stats.
Writes to performance/strategy_performance.json.

Useful for: which strategies work, which don't, what to scale up.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()


def main():
    journal = ROOT / "data_cache" / "trade_journal.jsonl"
    if not journal.exists():
        print("no trade_journal.jsonl — no trades to analyze")
        return 0
    # Per-strategy aggregation
    by_strategy = defaultdict(lambda: {
        "trades": 0, "wins": 0, "losses": 0,
        "total_pnl": 0.0, "max_win": 0.0, "max_loss": 0.0,
        "by_underlying": defaultdict(lambda: {"trades": 0, "pnl": 0.0}),
    })
    by_underlying = defaultdict(lambda: {
        "trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0,
    })
    by_day = defaultdict(lambda: {"trades": 0, "pnl": 0.0})
    all_pnls = []
    # FIX 2026-09-18 11:15: phantom-fill exclusion + counter. Phantom fills
    # happen when paper_client falls through to the Rs.1.00 fallback (chain
    # lookups failed, no live tick). These pollute the by_day / cumulative
    # return calculation. We now exclude phantom_price entries from the
    # P&L aggregations and track a phantom_count separately so the dashboard
    # can show how much was excluded.
    #
    # FIX 2026-09-18 15:55: dedup by order_id + use realized_delta for inline
    # fills. The previous code counted both inline fills (realized_delta) and
    # RECON/EOD entries (realized_pnl) which double-counted the same P&L
    # event. Now we:
    #   1. Dedupe by order_id (same fill logged twice → counted once)
    #   2. For inline fills (event=FILL, status=complete): use realized_delta
    #   3. For RECON entries: skip entirely (they re-report past events)
    #   4. For EOD entries: skip entirely (they backfill past events)
    # Result: by_day should match paper_state.realized_pnl (within rounding).
    phantom_count = 0
    phantom_pnl_excluded = 0.0
    suspect_count = 0
    recon_skipped = 0
    eod_skipped = 0
    dedupe_skipped = 0
    pre_reset_skipped = 0
    seen_order_ids: set[str] = set()
    inline_realized_delta_sum = 0.0  # for reconciliation panel
    reset_ts: str | None = None  # FIX 2026-09-18 16:00: skip entries before RESET

    # FIX 2026-09-18 16:00: two-pass scan. Pass 1 finds the most recent RESET
    # marker so we can skip journal entries from BEFORE that reset (those
    # correspond to a paper_state that's been wiped and can't be reconciled).
    with open(journal, "r", encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("event") == "RESET":
                ts = d.get("ts", "")
                if ts and (reset_ts is None or ts > reset_ts):
                    reset_ts = ts

    with open(journal, "r", encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            # FIX 2026-09-18 16:00: skip entries before the most recent
            # paper_state RESET. Those entries correspond to fills that
            # happened before the current session's paper_state baseline
            # (which was zeroed by the RESET). Including them inflates
            # the cumulative P&L above what's actually in cash.
            entry_ts = (
                d.get("ts", "")
                or d.get("filled_at", "")
                or d.get("closed_at", "")
                or d.get("placed_at", "")
            )
            if reset_ts and entry_ts and entry_ts < reset_ts:
                pre_reset_skipped += 1
                continue
            # Dedup by order_id (catches the same fill logged twice — we saw
            # this on Sep 15 with duplicate orphan-auto-close fills)
            oid = d.get("order_id", "") or d.get("trade_id", "")
            if oid and oid in seen_order_ids:
                dedupe_skipped += 1
                continue
            if oid:
                seen_order_ids.add(oid)
            is_phantom = bool(d.get("phantom_price", False))
            is_suspect = bool(d.get("suspect_price", False))
            if is_phantom:
                phantom_count += 1
                phantom_pnl_excluded += d.get("realized_pnl", 0) or 0
                # Skip phantom fills from all aggregates
                continue
            if is_suspect:
                suspect_count += 1
                # Suspect fills ARE included (less severe than phantom) but counted
            # Skip RECON entries (orphan recovery re-reports past events)
            if (d.get("trade_id", "") or "").startswith("RECON-"):
                recon_skipped += 1
                continue
            # Skip EOD backfill entries (they reconstruct past close P&L)
            if d.get("status") == "closed_eod":
                eod_skipped += 1
                continue
            # For inline fills, use realized_delta (matches paper_client._apply_fill
            # which sets _realized_delta). Fall back to realized_pnl for older
            # fills that don't have realized_delta. We consider any entry that
            # has a realized_delta or realized_pnl > 0 OR < 0 as a fill, since
            # the test fixtures don't always set `event`.
            delta = d.get("realized_delta")
            pnl_field = d.get("realized_pnl")
            # Skip non-fill events explicitly (RESET markers, etc.)
            if d.get("event") in ("RESET", "MARK"):
                pnl = 0.0
            elif (delta is not None and delta != 0) or (pnl_field is not None and pnl_field != 0):
                if delta is not None and delta != 0:
                    pnl = float(delta)
                else:
                    pnl = float(pnl_field)
                inline_realized_delta_sum += pnl
            else:
                pnl = 0.0  # Pure opens have 0 P&L
            strategy = d.get("strategy") or d.get("legs", [{}])[0].get("tag", "unknown") or "unknown"
            underlying = d.get("underlying", "UNK")
            day = (d.get("closed_at", "") or d.get("filled_at", "") or d.get("ts", "") or "")[:10]
            s = by_strategy[strategy]
            s["trades"] += 1
            s["total_pnl"] += pnl
            s["max_win"] = max(s["max_win"], pnl)
            s["max_loss"] = min(s["max_loss"], pnl)
            if pnl > 0:
                s["wins"] += 1
            elif pnl < 0:
                s["losses"] += 1
            s["by_underlying"][underlying]["trades"] += 1
            s["by_underlying"][underlying]["pnl"] += pnl
            u = by_underlying[underlying]
            u["trades"] += 1
            u["total_pnl"] += pnl
            if pnl > 0:
                u["wins"] += 1
            elif pnl < 0:
                u["losses"] += 1
            if day:
                by_day[day]["trades"] += 1
                by_day[day]["pnl"] += pnl
            all_pnls.append(pnl)

    # Compute derived metrics
    for s in by_strategy.values():
        n = s["trades"]
        s["win_rate"] = round(s["wins"] / n, 4) if n else 0
        s["avg_pnl"] = round(s["total_pnl"] / n, 2) if n else 0
        s["by_underlying"] = dict(s["by_underlying"])
    for u in by_underlying.values():
        n = u["trades"]
        u["win_rate"] = round(u["wins"] / n, 4) if n else 0
        u["avg_pnl"] = round(u["total_pnl"] / n, 2) if n else 0

    sharpe = 0
    if len(all_pnls) > 5:
        import statistics
        try:
            mean = statistics.mean(all_pnls)
            stdev = statistics.stdev(all_pnls) if len(all_pnls) > 1 else 1
            sharpe = (mean / stdev * (252 ** 0.5)) if stdev > 0 else 0
        except Exception:
            pass

    output = {
        "ts": datetime.now().isoformat(),
        "n_trades": len(all_pnls),
        "total_pnl": round(sum(all_pnls), 2),
        "sharpe_30d": round(sharpe, 2),
        "by_strategy": dict(by_strategy),
        "by_underlying": dict(by_underlying),
        "by_day": dict(by_day),
        # FIX 2026-09-18 11:15: phantom-aware metadata. Shows how many phantom
        # fills were excluded from the aggregates so the user can see the
        # "honest" P&L vs the raw journal total.
        "phantom": {
            "count": phantom_count,
            "pnl_excluded_rs": round(phantom_pnl_excluded, 2),
            "suspect_count": suspect_count,
            "interpretation": (
                f"{phantom_count} phantom fills excluded "
                f"(would have contributed Rs.{phantom_pnl_excluded:,.2f}); "
                f"{suspect_count} suspect fills included but flagged."
            ),
        },
        # FIX 2026-09-18 15:55: reconciliation metadata. Tells the user
        # how the aggregator differs from paper_state.cash (the
        # authoritative source). If inline_realized_delta_sum ≈ paper_state
        # realized_pnl, the data is consistent. If not, paper_state was
        # reset (losing P&L history) or there's a journal bug.
        "reconciliation": {
            "inline_realized_delta_sum_rs": round(inline_realized_delta_sum, 2),
            "recon_entries_skipped": recon_skipped,
            "eod_entries_skipped": eod_skipped,
            "duplicate_order_ids_skipped": dedupe_skipped,
            "pre_reset_entries_skipped": pre_reset_skipped,
            "most_recent_reset_ts": reset_ts,
            "interpretation": (
                f"Sum of inline fills' realized_delta (post-reset): Rs.{inline_realized_delta_sum:,.2f}. "
                f"Skipped {recon_skipped} RECON entries, {eod_skipped} EOD backfill entries, "
                f"{dedupe_skipped} duplicate order_ids, and {pre_reset_skipped} pre-RESET entries. "
                f"Compare to paper_state.realized_pnl to verify consistency."
            ),
        },
    }

    out_path = ROOT / "data_cache" / "performance" / "strategy_performance.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out_path}")
    print()
    print("By strategy:")
    for strat, s in sorted(by_strategy.items(), key=lambda x: -x[1]["total_pnl"]):
        print(f"  {strat:30s} n={s['trades']:3d} wins={s['wins']:3d} avg=Rs.{s['avg_pnl']:>+7.2f} total=Rs.{s['total_pnl']:>+8.2f} win_rate={s['win_rate']:.1%}")
    print()
    print("By underlying:")
    for u, s in sorted(by_underlying.items(), key=lambda x: -x[1]["total_pnl"]):
        print(f"  {u:12s} n={s['trades']:3d} wins={s['wins']:3d} avg=Rs.{s['avg_pnl']:>+7.2f} total=Rs.{s['total_pnl']:>+8.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
