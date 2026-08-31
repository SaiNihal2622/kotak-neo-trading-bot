"""Weekly strategy review + auto-backtest.

Runs every Sunday evening. The LLM reviews the week's decisions, identifies
patterns, and backtests the top performers. Sends a Telegram weekly summary.

Schedule: Sun 18:00 IST (could be triggered by quant_service watch loop or cron).
Output: data_cache/performance/weekly_review.json
"""
from __future__ import annotations
import json
import re
from collections import Counter
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional

ROOT = Path("data_cache/performance")
DECISIONS_PATH = ROOT / "decisions.jsonl"
OUTPUT_PATH = ROOT / "weekly_review.json"


def get_week_range(end_date: Optional[date] = None) -> tuple[date, date]:
    """Return (monday, sunday) of the week containing end_date."""
    end_date = end_date or date.today()
    monday = end_date - timedelta(days=end_date.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def get_weekly_decisions(monday: date, sunday: date) -> list[dict]:
    """Load all decisions in the given week."""
    if not DECISIONS_PATH.exists():
        return []
    out = []
    for line in DECISIONS_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        try:
            rec_date = date.fromisoformat(rec.get("ts", "")[:10])
            if monday <= rec_date <= sunday:
                out.append(rec)
        except Exception:
            continue
    return out


def get_pattern_summary(decisions: list[dict]) -> dict:
    """Extract patterns from the week's decisions."""
    strategies = Counter()
    underlyings = Counter()
    outcomes_by_strategy = {}
    closes_by_day = Counter()
    for rec in decisions:
        if rec.get("status") != "closed":
            continue
        s = rec.get("strategy", "?")
        u = rec.get("underlying", "?")
        strategies[s] += 1
        underlyings[u] += 1
        outcomes_by_strategy.setdefault(s, {"win": 0, "loss": 0, "pnl": 0})
        outcomes_by_strategy[s][rec.get("outcome", "?")] = outcomes_by_strategy[s].get(rec.get("outcome", "?"), 0) + 1
        outcomes_by_strategy[s]["pnl"] += rec.get("pnl", 0) or 0
        try:
            d = rec.get("close_ts", rec.get("ts", ""))[:10]
            closes_by_day[d] += 1
        except Exception:
            pass
    return {
        "strategies": dict(strategies.most_common()),
        "underlyings": dict(underlyings.most_common()),
        "outcomes_by_strategy": outcomes_by_strategy,
        "trades_per_day": dict(closes_by_day),
    }


def get_top_patterns(decisions: list[dict]) -> list[dict]:
    """Identify the most profitable patterns from the week."""
    if not decisions:
        return []
    by_strat = {}
    for rec in decisions:
        if rec.get("status") != "closed":
            continue
        s = rec.get("strategy", "?")
        by_strat.setdefault(s, []).append({
            "pnl": rec.get("pnl", 0) or 0,
            "outcome": rec.get("outcome", "?"),
            "rationale": rec.get("rationale", "")[:200],
        })
    out = []
    for s, trades in by_strat.items():
        if len(trades) < 1:
            continue
        wins = [t for t in trades if t["outcome"] == "win"]
        losses = [t for t in trades if t["outcome"] == "loss"]
        total_pnl = sum(t["pnl"] for t in trades)
        win_rate = len(wins) / len(trades) if trades else 0
        if total_pnl > 0 and len(trades) >= 2:
            out.append({
                "strategy": s,
                "trades": len(trades),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round(win_rate, 3),
                "total_pnl": round(total_pnl, 2),
                "sample_rationale": trades[0]["rationale"] if trades else "",
            })
    return sorted(out, key=lambda x: x["total_pnl"], reverse=True)[:5]


def run_weekly_review() -> dict:
    """Run the full weekly review."""
    from performance_tracker import get_total_cost_today, get_drawdown_recent
    monday, sunday = get_week_range()
    decisions = get_weekly_decisions(monday, sunday)
    patterns = get_pattern_summary(decisions)
    top = get_top_patterns(decisions)
    cost_today = get_total_cost_today()
    dd = get_drawdown_recent()
    total_pnl = sum((r.get("pnl") or 0) for r in decisions if r.get("status") == "closed")
    wins = sum(1 for r in decisions if r.get("outcome") == "win")
    losses = sum(1 for r in decisions if r.get("outcome") == "loss")
    closed = wins + losses
    win_rate = wins / closed if closed else 0

    out = {
        "week": f"{monday.isoformat()} to {sunday.isoformat()}",
        "trades": len(decisions),
        "closed": closed,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 3),
        "realized_pnl": round(total_pnl, 2),
        "drawdown": dd,
        "cost_today": cost_today,
        "patterns": patterns,
        "top_patterns": top,
    }

    # If we have decisions, ask the LLM to review the week
    if decisions:
        try:
            import sys
            if "." not in sys.path:
                sys.path.insert(0, ".")
            from scripts.quant_service import call_llm_direct
            prompt = (
                f"Weekly review {monday} to {sunday}:\n"
                f"Trades: {len(decisions)}, closed: {closed}, wins/losses: {wins}/{losses}, win rate: {win_rate*100:.0f}%\n"
                f"Realized P&L: Rs.{total_pnl:+,.0f}\n"
                f"Strategies: {json.dumps(patterns['outcomes_by_strategy'])}\n"
                f"Top patterns: {json.dumps(top[:3])}\n\n"
                "Analyze the week: what worked, what didn't, what to change next week. "
                "Output a SHORT bulleted list (3-5 bullets). No JSON, plain text."
            )
            review = call_llm_direct(
                "You are a senior quant reviewing your weekly trading performance. Be data-driven, specific, and brief.",
                prompt,
                max_tokens=800
            )
            if review.get("ok"):
                out["llm_review"] = review.get("text", "")[:3000]
        except Exception as e:
            out["llm_review_error"] = str(e)

    OUTPUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def format_weekly_telegram(review: dict) -> str:
    """Format review for Telegram."""
    lines = [
        f"=== WEEKLY REVIEW {review.get('week')} ===",
        f"Trades: {review.get('trades', 0)} (closed: {review.get('closed', 0)})",
        f"Wins/Losses: {review.get('wins', 0)}/{review.get('losses', 0)} | Win rate: {review.get('win_rate', 0)*100:.0f}%",
        f"Realized P&L: Rs.{review.get('realized_pnl', 0):+,.0f}",
        f"Max drawdown: Rs.{review.get('drawdown', {}).get('max_dd', 0):,.0f}",
    ]
    if review.get("llm_review"):
        lines.append(f"\nLLM Self-Review:\n{review['llm_review'][:1500]}")
    if review.get("top_patterns"):
        lines.append("\nTop patterns:")
        for p in review["top_patterns"][:3]:
            lines.append(f"  {p['strategy']}: {p['trades']} trades, {p['win_rate']*100:.0f}% win, Rs.{p['total_pnl']:+,.0f}")
    return "\n".join(lines)


if __name__ == "__main__":
    review = run_weekly_review()
    print(format_weekly_telegram(review))
