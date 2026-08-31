"""Performance tracker for the LLM quant brain.

Tracks:
- Per-decision: P&L outcome (win/loss/breakeven), time-to-close
- Per-day: realized P&L, win rate, profit factor, max drawdown, Sharpe-like
- Per-strategy: edge by strategy type (iron_condor, long_pe, etc.)
- Token usage: LLM call count, total cost estimate

Output: data_cache/performance/{daily,decisions,strategies}.json
Telegram: end-of-day summary
"""
from __future__ import annotations
import json
import math
from collections import deque
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path("data_cache/performance")
ROOT.mkdir(parents=True, exist_ok=True)
DECISIONS_PATH = ROOT / "decisions.jsonl"
DAILY_PATH = ROOT / "daily.json"
STRATEGIES_PATH = ROOT / "strategies.json"
COST_PATH = ROOT / "cost.json"


def record_decision(decision_id: str, ts: str, action_type: str, strategy: str, underlying: str,
                    rationale: str, max_hold_minutes: int = 240,
                    tags: Optional[dict] = None) -> None:
    """Record a new LLM decision. status: 'pending' until outcome known.

    tags (optional): setup_type, iv_regime, dte (days to expiry), exit_reason, etc.
    """
    rec = {
        "decision_id": decision_id,
        "ts": ts,
        "action_type": action_type,
        "strategy": strategy or "custom",
        "underlying": underlying,
        "rationale": rationale[:300],
        "max_hold_minutes": max_hold_minutes,
        "status": "pending",
        "entry_premium": None,
        "exit_premium": None,
        "pnl": None,
        "outcome": None,  # "win" | "loss" | "breakeven"
        "close_ts": None,
        "tags": tags or {},
    }
    with open(DECISIONS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def record_outcome(decision_id: str, pnl: float) -> None:
    """Record outcome (pnl) for a decision. Idempotent."""
    if not DECISIONS_PATH.exists():
        return
    lines = DECISIONS_PATH.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("decision_id") == decision_id:
            rec["pnl"] = pnl
            rec["outcome"] = "win" if pnl > 50 else ("loss" if pnl < -50 else "breakeven")
            rec["status"] = "closed"
            rec["close_ts"] = datetime.now().isoformat()
        out.append(rec)
    DECISIONS_PATH.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n", encoding="utf-8")


def get_daily_summary(target_date: Optional[date] = None) -> dict:
    """Compute daily performance summary."""
    target_date = target_date or date.today()
    if not DECISIONS_PATH.exists():
        return {"date": target_date.isoformat(), "trades": 0, "realized_pnl": 0}
    lines = DECISIONS_PATH.read_text(encoding="utf-8").splitlines()
    today_decisions = []
    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("ts", "").startswith(target_date.isoformat()):
            today_decisions.append(rec)
    pnl = sum(r.get("pnl") or 0 for r in today_decisions if r.get("status") == "closed")
    wins = [r for r in today_decisions if r.get("outcome") == "win"]
    losses = [r for r in today_decisions if r.get("outcome") == "loss"]
    breakevens = [r for r in today_decisions if r.get("outcome") == "breakeven"]
    closed_count = len(wins) + len(losses) + len(breakevens)
    win_rate = len(wins) / closed_count if closed_count > 0 else 0
    profit_factor = (
        sum(r["pnl"] for r in wins) / max(1, abs(sum(r["pnl"] for r in losses)))
        if losses else (sum(r["pnl"] for r in wins) if wins else 0)
    )
    avg_win = sum(r["pnl"] for r in wins) / max(1, len(wins))
    avg_loss = sum(r["pnl"] for r in losses) / max(1, len(losses))
    return {
        "date": target_date.isoformat(),
        "trades": len(today_decisions),
        "closed": closed_count,
        "wins": len(wins),
        "losses": len(losses),
        "breakevens": len(breakevens),
        "win_rate": round(win_rate, 3),
        "realized_pnl": round(pnl, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "expectancy": round((win_rate * avg_win) - ((1 - win_rate) * abs(avg_loss)), 2),
    }


def get_strategy_performance() -> dict:
    """Performance by strategy type."""
    if not DECISIONS_PATH.exists():
        return {}
    lines = DECISIONS_PATH.read_text(encoding="utf-8").splitlines()
    by_strategy = {}
    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("status") != "closed":
            continue
        s = rec.get("strategy", "unknown")
        if s not in by_strategy:
            by_strategy[s] = {"wins": 0, "losses": 0, "pnl": 0, "count": 0}
        by_strategy[s]["count"] += 1
        by_strategy[s]["pnl"] += rec.get("pnl", 0) or 0
        if rec.get("outcome") == "win":
            by_strategy[s]["wins"] += 1
        elif rec.get("outcome") == "loss":
            by_strategy[s]["losses"] += 1
    for s, v in by_strategy.items():
        total = v["wins"] + v["losses"]
        v["win_rate"] = round(v["wins"] / total, 3) if total > 0 else 0
        v["pnl"] = round(v["pnl"], 2)
    return by_strategy


def get_drawdown_recent(days: int = 30) -> dict:
    """Compute max drawdown over the recent window."""
    if not DECISIONS_PATH.exists():
        return {"max_dd": 0, "current_dd": 0, "in_drawdown": False}
    lines = DECISIONS_PATH.read_text(encoding="utf-8").splitlines()
    pnls = []
    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("status") == "closed" and rec.get("pnl") is not None:
            pnls.append((rec.get("ts", ""), rec["pnl"]))
    if not pnls:
        return {"max_dd": 0, "current_dd": 0, "in_drawdown": False}
    # Build cumulative P&L
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for ts, pnl in pnls[-200:]:  # last 200 trades
        cum += pnl
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
    current_dd = peak - cum
    return {
        "max_dd": round(max_dd, 2),
        "current_dd": round(current_dd, 2),
        "in_drawdown": current_dd > 1000,
        "peak_pnl": round(peak, 2),
        "current_pnl": round(cum, 2),
    }


def record_llm_cost(usage: dict) -> None:
    """Log LLM token usage and cost. usage has input_tokens, output_tokens, cache_read."""
    rec = {
        "ts": datetime.now().isoformat(),
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cache_read": usage.get("cache_read_input_tokens", 0),
        "cache_creation": usage.get("cache_creation_input_tokens", 0),
        # Cost estimates (Anthropic Sonnet pricing as of 2026-08)
        "cost_usd": round(
            (usage.get("input_tokens", 0) - usage.get("cache_read_input_tokens", 0)) * 0.000003 +
            usage.get("cache_read_input_tokens", 0) * 0.0000003 +
            usage.get("output_tokens", 0) * 0.000015,
            6
        ),
    }
    with open(COST_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def get_total_cost_today() -> dict:
    """Sum of today's LLM cost."""
    if not COST_PATH.exists():
        return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0}
    today = date.today().isoformat()
    total = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    for line in COST_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("ts", "").startswith(today):
            total["calls"] += 1
            total["input_tokens"] += rec.get("input_tokens", 0)
            total["output_tokens"] += rec.get("output_tokens", 0)
            total["cost_usd"] += rec.get("cost_usd", 0)
    total["cost_usd"] = round(total["cost_usd"], 4)
    return total


def save_daily_snapshot() -> dict:
    """Snapshot end-of-day summary."""
    summary = get_daily_summary()
    summary["drawdown"] = get_drawdown_recent()
    summary["strategies"] = get_strategy_performance()
    summary["llm_cost_today"] = get_total_cost_today()
    DAILY_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    STRATEGIES_PATH.write_text(json.dumps(summary["strategies"], indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


# --- Circuit breakers ---

def check_daily_loss_limit(capital: float, max_loss_pct: float = 0.03) -> tuple[bool, float]:
    """Returns (should_pause_today, current_loss_pct)."""
    summary = get_daily_summary()
    realized = summary.get("realized_pnl", 0)
    if realized >= 0:
        return (False, 0.0)
    loss_pct = abs(realized) / capital
    return (loss_pct > max_loss_pct, round(loss_pct, 4))


def check_consecutive_losses(max_consecutive: int = 3) -> tuple[bool, int]:
    """Returns (should_pause, current_consecutive_loss_count)."""
    if not DECISIONS_PATH.exists():
        return (False, 0)
    lines = DECISIONS_PATH.read_text(encoding="utf-8").splitlines()
    # Get last N closed trades
    recent = []
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("status") == "closed":
            recent.append(rec)
        if len(recent) >= max_consecutive + 1:
            break
    consecutive = 0
    for rec in recent:
        if rec.get("outcome") == "loss":
            consecutive += 1
        else:
            break
    return (consecutive >= max_consecutive, consecutive)


def should_pause_new_entries(capital: float) -> tuple[bool, str]:
    """Master circuit breaker. Returns (should_pause, reason)."""
    # Daily loss limit
    daily_hit, daily_pct = check_daily_loss_limit(capital)
    if daily_hit:
        return (True, f"daily_loss_{daily_pct*100:.1f}% > 3%")
    # Consecutive losses
    consec_hit, consec = check_consecutive_losses()
    if consec_hit:
        return (True, f"consecutive_losses={consec} >= 3")
    # Max position cost
    # This is checked in __main__.py block 1c directly (5% per position)
    return (False, "ok")


if __name__ == "__main__":
    # Self-test
    rec1 = {"decision_id": "test-1", "ts": datetime.now().isoformat(), "action_type": "OPEN", "strategy": "iron_condor", "underlying": "NIFTY", "rationale": "test", "max_hold_minutes": 240, "status": "pending", "entry_premium": None, "exit_premium": None, "pnl": None, "outcome": None, "close_ts": None}
    DECISIONS_PATH.write_text(json.dumps(rec1) + "\n", encoding="utf-8")
    record_outcome("test-1", 1500)
    print("Daily:", get_daily_summary())
    print("Drawdown:", get_drawdown_recent())
    print("Should pause:", should_pause_new_entries(100000))
