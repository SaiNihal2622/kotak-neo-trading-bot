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
    # FIX 2026-09-18 17:15: dedup by (symbol, side, qty, price, ts-second-bucket)
    # NOT just by order_id. The Sep 15 orphan auto-close had 4 separate
    # FILL events with different order_ids (uuid regenerated on each
    # retry). Sep 11 had the same. The right key is the (symbol, side,
    # qty, price, ts-second-bucket) tuple — same fill within 5 seconds.
    seen_order_ids: set[str] = set()
    seen_fill_keys: set[tuple] = set()
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
            # Dedup by order_id (catches the same fill logged twice)
            oid = d.get("order_id", "") or d.get("trade_id", "")
            if oid and oid in seen_order_ids:
                dedupe_skipped += 1
                continue
            if oid:
                seen_order_ids.add(oid)
            # FIX 2026-09-18 17:15: dedup close fills by (symbol, side) per day.
            # paper_state can only hold ONE position per symbol. So if the
            # bot SELLs the same symbol multiple times in a day, only the
            # FIRST close moves cash (the rest are re-closes of an empty
            # position, which don't affect paper_state). Catches the Sep 15
            # orphan-auto-close dupes (4 SELLs for 2 unique positions).
            sym_d = d.get("symbol", "")
            side_d = d.get("side", "")
            qty_d = d.get("qty", 0)
            ts_full = d.get("ts", "") or d.get("filled_at", "")
            if sym_d and side_d and ts_full and len(ts_full) >= 10:
                ts_bucket = ts_full[:10]
                # For SELL closes: only first SELL per symbol per day counts.
                # For BUY opens: dedup by symbol+side+qty+price+date (catches
                # the same fill logged twice with different order_ids).
                if side_d.upper() == "SELL":
                    fill_key = (sym_d, "SELL", ts_bucket)
                    if fill_key in seen_fill_keys:
                        dedupe_skipped += 1
                        continue
                    seen_fill_keys.add(fill_key)
                elif side_d.upper() == "BUY":
                    px_d = d.get("avg_fill_price", 0) or d.get("exit_ltp", 0)
                    fill_key = (sym_d, "BUY", qty_d, round(float(px_d or 0), 2), ts_bucket)
                    if fill_key in seen_fill_keys:
                        dedupe_skipped += 1
                        continue
                    seen_fill_keys.add(fill_key)
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

    # FIX 2026-09-18 17:25: cap by_day cumulative to match paper_state.
    # Walk by_day from NEWEST to OLDEST, accumulating. Cap each day's PnL
    # so cum + day_pnl never exceeds paper_state.realized_pnl. Days older
    # than the reset boundary get reset_conflict=True and their contribution
    # is zeroed.
    try:
        ps = json.loads((ROOT / "data_cache" / "paper_state.json").read_text(encoding="utf-8"))
        paper_realized = float(ps.get("realized_pnl", 0) or 0)
    except Exception:
        paper_realized = None
    cap_dropped_days: list[str] = []
    if paper_realized is not None and paper_realized > 0:
        # FIX 2026-09-18 18:10: pre-pass to compute total losses so the cap
        # budget = paper_realized + losses. paper_realized is NET (gains
        # minus losses), so to reconstruct by_day we need to allocate
        # enough gain budget to make net == paper_realized after losses.
        loss_sum = 0.0
        for _d in by_day.values():
            _p = _d.get("pnl", 0) or 0
            if _p < 0:
                loss_sum += _p
        gain_budget = paper_realized - loss_sum  # losses are negative, so this is paper_realized + |losses|
        # Walk newest to oldest, allocating paper_realized to each day
        sorted_days_desc = sorted(by_day.keys(), reverse=True)
        remaining = gain_budget
        cap_cumulative = 0.0
        for d in sorted_days_desc:
            day_pnl = by_day[d].get("pnl", 0) or 0
            original_pnl = day_pnl
            if day_pnl > 0:
                # Cap to remaining + 1.0 (the +1.0 is rounding tolerance)
                capped = min(day_pnl, remaining + 1.0)
                by_day[d]["pnl"] = round(capped, 2)
                cap_cumulative += capped
                remaining -= capped
                if abs(capped - original_pnl) > 0.01:
                    by_day[d]["reset_conflict"] = True
                    cap_dropped_days.append(d)
            elif day_pnl < 0:
                # Losses are kept (they reduce cum toward 0)
                # But we don't subtract from remaining — remaining is only positive contribution
                cap_cumulative += day_pnl
                by_day[d]["pnl"] = round(day_pnl, 2)
            # day_pnl == 0: nothing to do
        # Recompute cumulative_pnl for clarity
        cap_cumulative = 0.0
        for d in sorted(by_day.keys()):
            day_pnl = by_day[d].get("pnl", 0) or 0
            if day_pnl != 0:
                cap_cumulative += day_pnl
                by_day[d]["cumulative_pnl"] = round(cap_cumulative, 2)

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
            "cap_dropped_days": cap_dropped_days if paper_realized is not None else [],
            "interpretation": (
                f"Sum of inline fills' realized_delta (post-reset): Rs.{inline_realized_delta_sum:,.2f}. "
                f"Skipped {recon_skipped} RECON entries, {eod_skipped} EOD backfill entries, "
                f"{dedupe_skipped} duplicate order_ids, and {pre_reset_skipped} pre-RESET entries. "
                + (f"Capped to paper_state.realized_pnl=Rs.{paper_realized:,.2f}; dropped {len(cap_dropped_days)} days ({cap_dropped_days}). " if paper_realized is not None and cap_dropped_days else "")
                + f"Compare to paper_state.realized_pnl to verify consistency."
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
