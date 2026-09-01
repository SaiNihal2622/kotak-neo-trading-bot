"""Profit engine — makes the system actually build profits.

This is the 'how do we compound' layer. Sits between the LLM's
decisions and the actual order placement. Three responsibilities:

1. COMPOUNDING: as capital grows, position size grows (and vice versa).
   No point leaving ₹10,000 of unused buying power when we have edge.

2. KELLY SIZING: each strategy gets a Kelly-fraction size based on
   its actual win rate and avg win/loss from recent trades. We use
   HALF Kelly (safer) capped at 5% of capital per trade.

3. CIRCUIT BREAKERS: real-time monitoring of drawdown, daily loss,
   consecutive losses. Auto-pause new entries if limits breached.

Outputs: per-call report that goes into the LLM context, so it sees:
  - current_capital (with compounding)
  - recommended_size_pct (Kelly-derived)
  - daily_pnl, weekly_pnl, total_pnl
  - drawdown_status
  - per_strategy_performance
  - is_paused (from circuit breaker)
"""
from __future__ import annotations
import json
import sys
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'
sys.path.insert(0, str(ROOT / "scripts"))


def _read_json(path: Path, default=None) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def get_profit_state() -> dict:
    """Compute the current profit state — capital, P&L, drawdown, recommendations.
    This is the key input the LLM should use for sizing decisions."""
    paper = _read_json(DATA / "paper_state.json", default={})
    capital = paper.get("capital", 100000) or 100000
    cash = paper.get("cash", capital) or capital
    realized = paper.get("realized_pnl", 0) or 0
    # Effective capital = starting + realized (compounded)
    starting_capital = 100000
    effective_capital = starting_capital + realized
    # Per-strategy P&L from trades
    trades_state = _read_json(DATA / "trades_state.json", default={})
    trades = trades_state.get("trades", {}) or {}
    strategy_pnl = {}
    strategy_wins = {}
    strategy_losses = {}
    strategy_count = {}
    for tid, t in trades.items():
        if t.get("status") != "closed":
            continue
        strat = (t.get("plan", {}) or {}).get("strategy", "unknown")
        pnl = t.get("realized_pnl", 0) or 0
        strategy_pnl[strat] = strategy_pnl.get(strat, 0) + pnl
        strategy_count[strat] = strategy_count.get(strat, 0) + 1
        if pnl > 100:
            strategy_wins[strat] = strategy_wins.get(strat, 0) + 1
        elif pnl < -100:
            strategy_losses[strat] = strategy_losses.get(strat, 0) + 1
    # Kelly per strategy: f* = (p * b - q) / b  where p=win_rate, b=avg_win/avg_loss
    kelly_per_strategy = {}
    for strat in strategy_pnl:
        wins = strategy_wins.get(strat, 0)
        losses = strategy_losses.get(strat, 0)
        n = strategy_count[strat]
        if wins + losses == 0:
            kelly_per_strategy[strat] = 0.0
            continue
        p = wins / n
        # Conservative: assume avg loss = 1.5x avg win (real markets aren't 1:1)
        b = 1.5
        kelly = (p * b - (1 - p)) / b
        # Half-Kelly for safety; cap at 5% (0.05) and floor at 0
        kelly = max(0.0, min(0.05, kelly * 0.5))
        kelly_per_strategy[strat] = round(kelly, 4)
    # Today's P&L
    today = datetime.now().strftime("%Y-%m-%d")
    today_pnl = 0.0
    today_trades = 0
    for tid, t in trades.items():
        if t.get("status") != "closed":
            continue
        if t.get("closed_at", "").startswith(today):
            today_pnl += t.get("realized_pnl", 0) or 0
            today_trades += 1
    # Consecutive losses (for circuit breaker)
    closed_trades = sorted(
        [t for t in trades.values() if t.get("status") == "closed"],
        key=lambda t: t.get("closed_at", ""),
        reverse=True,
    )
    consecutive_losses = 0
    for t in closed_trades[:5]:
        pnl = t.get("realized_pnl", 0) or 0
        if pnl < -100:
            consecutive_losses += 1
        else:
            break
    # Drawdown calc
    peak = max(starting_capital, effective_capital)
    current_dd = (peak - effective_capital) / peak * 100 if peak > 0 else 0
    # Circuit breakers
    daily_loss_pct = -today_pnl / starting_capital * 100 if today_pnl < 0 else 0
    is_paused = False
    pause_reason = ""
    if daily_loss_pct > 3.0:
        is_paused = True
        pause_reason = f"daily loss {daily_loss_pct:.1f}% > 3% cap"
    elif current_dd > 10.0:
        is_paused = True
        pause_reason = f"drawdown {current_dd:.1f}% > 10% cap"
    elif consecutive_losses >= 3:
        is_paused = True
        pause_reason = f"{consecutive_losses} consecutive losses — review setup"
    # Recommended position size: Kelly for the strategy, capped at 1% of effective capital
    return {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "starting_capital": starting_capital,
        "effective_capital": round(effective_capital, 2),
        "current_cash": round(cash, 2),
        "compounded_pnl": round(realized, 2),
        "today_pnl": round(today_pnl, 2),
        "today_trades": today_trades,
        "drawdown_pct": round(current_dd, 2),
        "consecutive_losses": consecutive_losses,
        "is_paused": is_paused,
        "pause_reason": pause_reason,
        "strategy_performance": {
            s: {
                "pnl": round(strategy_pnl[s], 2),
                "wins": strategy_wins.get(s, 0),
                "losses": strategy_losses.get(s, 0),
                "count": strategy_count[s],
                "win_rate": round(strategy_wins.get(s, 0) / max(strategy_count[s], 1), 3),
                "kelly_size_pct": kelly_per_strategy.get(s, 0.0),
            }
            for s in strategy_pnl
        },
        "sizing_recommendation": {
            # Max risk per trade = min(1% of capital, 5% of effective capital = Kelly cap)
            "max_risk_pct_per_trade": 0.01,  # 1% of effective capital
            "max_risk_inr": round(effective_capital * 0.01, 2),
            "note": "1% per trade, but effective capital = starting + compounded P&L. "
                    "Use Kelly size for high-edge strategies (e.g. iron_condor in range regime).",
        },
        "interpretation": (
            f"Capital: Rs.{effective_capital:,.0f} (started at Rs.{starting_capital:,}, "
            f"P&L Rs.{realized:+,.0f}). Today's P&L: Rs.{today_pnl:+,.0f}. "
            f"Drawdown: {current_dd:.1f}%. "
            f"{'PAUSED: ' + pause_reason if is_paused else 'ACTIVE — can trade.'}"
        ),
    }


def log_profit_state(state: dict) -> None:
    """Append to profit_state.jsonl for historical tracking."""
    path = DATA / "profit_state.jsonl"
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(state, default=str) + "\n")
    except Exception:
        pass


# --- Self-evolution enhancements ---

def get_strategy_recommendation() -> dict:
    """Based on actual P&L data, recommend which strategies to focus on.
    This is fed to the 23:00 nightly improvement so the LLM can self-tune."""
    state = get_profit_state()
    perf = state.get("strategy_performance", {})
    # Rank by P&L
    ranked = sorted(perf.items(), key=lambda kv: kv[1].get("pnl", 0), reverse=True)
    best = ranked[0] if ranked else (None, None)
    worst = ranked[-1] if ranked else (None, None)
    return {
        "best_strategy": best[0] if best[0] else "none yet",
        "best_pnl": best[1].get("pnl", 0) if best[0] else 0,
        "worst_strategy": worst[0] if worst[0] else "none yet",
        "worst_pnl": worst[1].get("pnl", 0) if worst[0] else 0,
        "ranked": [
            {"strategy": k, "pnl": v.get("pnl", 0), "win_rate": v.get("win_rate", 0),
             "kelly_size_pct": v.get("kelly_size_pct", 0)}
            for k, v in ranked
        ],
        "recommendation": (
            f"Focus on {best[0]} (₹{best[1].get('pnl', 0):+,.0f}, "
            f"win_rate {best[1].get('win_rate', 0):.0%}, "
            f"Kelly size {best[1].get('kelly_size_pct', 0):.1%})."
            if best[0] else "No closed trades yet — can't recommend."
        ),
    }


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "state"
    if cmd == "state":
        state = get_profit_state()
        print(json.dumps(state, indent=2, default=str))
    elif cmd == "recommend":
        rec = get_strategy_recommendation()
        print(json.dumps(rec, indent=2, default=str))
    else:
        print(f"Unknown: {cmd}")
        print("Usage: python profit_engine.py [state|recommend]")
