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

    with open(journal, "r", encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            pnl = d.get("realized_pnl", 0) or 0
            strategy = d.get("strategy") or d.get("legs", [{}])[0].get("tag", "unknown") or "unknown"
            underlying = d.get("underlying", "UNK")
            day = (d.get("closed_at", "") or "")[:10]
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
