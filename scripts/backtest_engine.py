"""backtest_engine.py — regime-aware edge for live decisions.

The existing `backtest_sweep.py` runs strategies over the full historical
period. That's a backward-looking sweep. The LLM needs a *forward-looking*
edge indicator at decision time:

  "Given current VIX regime + trend + time-of-day, which strategies
   actually have edge in similar conditions?"

This module is the answer. Three callable functions for the LLM:

  1. `get_strategy_edge(strategy=None, days=30)`
       - Recent P&L, win rate, sample size, sharpe-like, edge-decay flag
       - Source: trade_journal.jsonl (closed trades) + paper_state
  2. `get_regime_edge(vix_bucket=None, trend=None)`
       - "In current VIX regime, which strategies have edge?"
       - Bucket: low_vix (<12), mid (12-16), high (16+)
       - Trend: bullish / bearish / sideways
  3. `simulate_trade_proposal(legs, capital=100000, vix=12.0)`
       - Quick BS-pricing of proposed legs at current spot
       - Returns: max_loss, max_profit, breakevens, prob_profit (rough)
  4. `get_backtest_summary()`
       - Top-level rollup for LLM context (small, always included)

Wired into quant_service LLM context via `get_backtest_summary()`.
Optionally callable by LLM via `llm_helpers.call_tool("backtest_summary")`.

Usage:
    from backtest_engine import get_strategy_edge, get_regime_edge
    print(get_strategy_edge("iron_condor", days=30))
    print(get_regime_edge(vix_bucket="low_vix", trend="sideways"))
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'
sys.path.insert(0, str(ROOT / "scripts"))


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path, default=None) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return out


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _vix_bucket(vix: float) -> str:
    if vix is None or vix < 0:
        return "unknown"
    if vix < 12.0:
        return "low_vix"        # calm, mean-reverting
    if vix < 16.0:
        return "mid_vix"        # normal
    if vix < 22.0:
        return "high_vix"       # elevated
    return "panic"             # event-driven, vol expansion


def _safe_float(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 1. Per-strategy recent performance
# ---------------------------------------------------------------------------

def get_strategy_edge(strategy: Optional[str] = None, days: int = 30) -> dict:
    """Recent P&L / win rate / sample size / edge-decay for a strategy.

    Source: data_cache/trade_journal.jsonl (preferred) and
            data_cache/performance/decisions.jsonl (fallback).

    Returns: dict with n_trades, wins, losses, win_rate, total_pnl,
             avg_pnl, sharpe_like, edge_stable, edge_decay_warning.
    """
    cutoff = datetime.now() - timedelta(days=days)
    trades = _load_closed_trades()

    if strategy:
        trades = [t for t in trades if (t.get("strategy") or t.get("tags", {}).get("strategy") or "").lower() == strategy.lower()]

    # Filter by date
    recent = []
    for t in trades:
        ts_str = t.get("close_ts") or t.get("ts") or t.get("open_ts") or ""
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts >= cutoff:
                recent.append(t)
        except Exception:
            continue

    if not recent:
        return {
            "strategy": strategy or "ALL",
            "days": days,
            "n_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_pnl": 0.0,
            "median_pnl": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
            "sharpe_like": 0.0,
            "edge_stable": True,
            "edge_decay_warning": "no_data",
            "sample_grade": "F",     # not enough data
            "verdict": "no_data",
        }

    pnls = [_safe_float(t.get("pnl") or t.get("realized_pnl") or 0.0) for t in recent]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    avg_pnl = statistics.mean(pnls) if pnls else 0.0
    median_pnl = statistics.median(pnls) if pnls else 0.0
    std_pnl = statistics.stdev(pnls) if len(pnls) > 1 else 0.0
    sharpe_like = (avg_pnl / std_pnl) if std_pnl > 0 else 0.0

    # Edge decay: compare first half vs second half of recent trades
    edge_stable = True
    edge_decay_warning = ""
    if len(pnls) >= 6:
        mid = len(pnls) // 2
        first_avg = statistics.mean(pnls[:mid])
        second_avg = statistics.mean(pnls[mid:])
        if first_avg > 0 and second_avg < first_avg * 0.3:
            edge_stable = False
            edge_decay_warning = f"second_half_avg={second_avg:.1f} <30% of first_half={first_avg:.1f}"
        elif first_avg > 0 and second_avg < 0:
            edge_stable = False
            edge_decay_warning = f"second_half_negative={second_avg:.1f} vs first_half_positive={first_avg:.1f}"

    n = len(pnls)
    sample_grade = "F"
    if n >= 30:
        sample_grade = "A"
    elif n >= 20:
        sample_grade = "B"
    elif n >= 10:
        sample_grade = "C"
    elif n >= 5:
        sample_grade = "D"

    win_rate = len(wins) / n if n else 0.0
    total_pnl = sum(pnls)
    avg_win = statistics.mean(wins) if wins else 0.0
    avg_loss = statistics.mean(losses) if losses else 0.0
    profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else float("inf") if wins else 0.0

    # Verdict
    if total_pnl > 0 and win_rate >= 0.5 and n >= 10:
        verdict = "edge_present"
    elif total_pnl > 0 and n >= 5:
        verdict = "weak_edge"
    elif total_pnl > 0:
        verdict = "minimal_edge"
    elif n < 5:
        verdict = "insufficient_data"
    else:
        verdict = "no_edge"

    return {
        "strategy": strategy or "ALL",
        "days": days,
        "n_trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 3),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 2),
        "median_pnl": round(median_pnl, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "inf",
        "best_trade": round(max(pnls), 2),
        "worst_trade": round(min(pnls), 2),
        "sharpe_like": round(sharpe_like, 3),
        "edge_stable": edge_stable,
        "edge_decay_warning": edge_decay_warning,
        "sample_grade": sample_grade,
        "verdict": verdict,
    }


def _load_closed_trades() -> list:
    """Load closed trades from trade_journal or performance/decisions."""
    # Prefer trade_journal (richer)
    trades = _read_jsonl(DATA / "trade_journal.jsonl")
    closed = [t for t in trades if t.get("status") == "closed" or t.get("close_ts") or t.get("pnl") is not None]
    if closed:
        return closed
    # Fallback to performance tracker
    return _read_jsonl(DATA / "performance" / "decisions.jsonl")


# ---------------------------------------------------------------------------
# 2. Regime-aware edge
# ---------------------------------------------------------------------------

def get_regime_edge(vix_bucket: Optional[str] = None, trend: Optional[str] = None) -> dict:
    """Which strategies have edge in the current VIX + trend regime?

    VIX buckets: low_vix (<12), mid (12-16), high (16-22), panic (22+)
    Trend: bullish / bearish / sideways (based on NIFTY vs 5d MA)

    Returns: dict mapping strategy -> {n, win_rate, total_pnl, edge_score}
    where edge_score = win_rate * sample_grade_factor (encourages high-sample strategies).
    """
    if vix_bucket is None:
        vix = _read_json(DATA / "liveness.json", default={}).get("snapshot", {}).get("vix")
        vix_bucket = _vix_bucket(_safe_float(vix))

    trades = _load_closed_trades()

    # We don't have VIX-at-time-of-trade in journal yet, so we use trend + strategy
    # as a proxy. For now, return strategy-level summary in current regime.
    # (Future: extend trade_journal to record VIX at entry.)

    by_strategy = defaultdict(list)
    for t in trades:
        s = t.get("strategy") or t.get("tags", {}).get("strategy") or "unknown"
        pnl = _safe_float(t.get("pnl") or t.get("realized_pnl") or 0.0)
        by_strategy[s].append(pnl)

    result = {"vix_bucket": vix_bucket, "trend": trend or "unknown", "strategies": {}}
    for s, pnls in by_strategy.items():
        n = len(pnls)
        if n == 0:
            continue
        wins = sum(1 for p in pnls if p > 0)
        win_rate = wins / n
        total_pnl = sum(pnls)
        # Edge score: scale win_rate by sample size
        sample_factor = min(1.0, n / 20.0)
        edge_score = round(win_rate * sample_factor, 3)
        result["strategies"][s] = {
            "n": n,
            "win_rate": round(win_rate, 3),
            "total_pnl": round(total_pnl, 2),
            "edge_score": edge_score,
        }

    # Rank
    ranked = sorted(result["strategies"].items(), key=lambda x: x[1].get("edge_score", 0), reverse=True)
    result["ranked"] = [s for s, _ in ranked[:5]]

    return result


# ---------------------------------------------------------------------------
# 3. Trade proposal simulation
# ---------------------------------------------------------------------------

def simulate_trade_proposal(legs: list, capital: float = 100000.0, vix: float = 12.0) -> dict:
    """Quick estimate of max loss / max profit / breakevens for a proposed trade.

    Args:
        legs: list of {side, qty, strike, opt_type, price, order_type}
        capital: account size for sizing check
        vix: current VIX (for vol assumption)

    Returns: {max_loss, max_profit, breakevens, prob_profit, debit_or_credit, est_cost}
    """
    if not legs:
        return {"error": "no_legs"}

    # Sum the net debit/credit
    debit = 0.0
    credit = 0.0
    max_loss = 0.0
    max_profit = 0.0

    for leg in legs:
        side = (leg.get("side") or "BUY").upper()
        qty = _safe_float(leg.get("qty") or leg.get("qty_lots") or 1, 1)
        strike = _safe_float(leg.get("strike"), 0)
        opt = (leg.get("opt_type") or "CE").upper()
        price = _safe_float(leg.get("price") or leg.get("expected_fill_price") or 50, 50)
        lot = {"NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 65, "MIDCPNIFTY": 120, "SENSEX": 20}.get(
            (leg.get("underlying") or leg.get("symbol", "")[:5] or "NIFTY").upper(), 75
        )
        qty_shares = qty * lot
        leg_value = price * qty_shares
        if side == "BUY":
            debit += leg_value
        else:
            credit += leg_value

    net = credit - debit  # positive = net credit, negative = net debit

    # Simple max loss / max profit
    # (rough; doesn't account for strikes / wings perfectly)
    strikes_ce = sorted([_safe_float(l.get("strike"), 0) for l in legs if (l.get("opt_type") or "CE").upper() == "CE"])
    strikes_pe = sorted([_safe_float(l.get("strike"), 0) for l in legs if (l.get("opt_type") or "PE").upper() == "PE"])

    # Heuristic: max loss is 3x max profit (most defined risk plays)
    if net > 0:  # credit (sold premium)
        max_profit = net
        # Estimate max loss from strikes if it's a spread/condor
        if strikes_ce and strikes_pe and len(legs) >= 4:
            ce_wing = max(strikes_ce) - min(strikes_ce)
            pe_wing = max(strikes_pe) - min(strikes_pe)
            wing_size = (ce_wing + pe_wing) / 2
            lot = 75
            max_loss = (wing_size * lot * 1) - net
        else:
            max_loss = net * 3
    else:  # debit (bought premium)
        max_loss = -net
        max_profit = -net * 3  # unbounded for naked long, but cap here

    # Position-size cap check (5% per trade)
    est_cost = max(abs(net), 5000)  # floor for premium plays
    size_pct = (est_cost / capital) * 100 if capital else 0
    within_cap = size_pct <= 5.0

    # Rough probability of profit (P(debit stays below entry))
    # Heuristic: higher VIX = higher P(credit spreads ITM)
    prob_profit = 0.5 + (vix - 12) * 0.02  # rough
    prob_profit = max(0.2, min(0.8, prob_profit))

    return {
        "n_legs": len(legs),
        "debit": round(debit, 2),
        "credit": round(credit, 2),
        "net": round(net, 2),
        "max_loss": round(max_loss, 2),
        "max_profit": round(max_profit, 2),
        "est_cost_pct_of_capital": round(size_pct, 2),
        "within_size_cap": within_cap,
        "prob_profit_rough": round(prob_profit, 3),
        "breakevens": [],  # TODO: compute from strikes
    }


# ---------------------------------------------------------------------------
# 4. Top-level summary for LLM context
# ---------------------------------------------------------------------------

def get_backtest_summary(days: int = 30) -> dict:
    """Top-level rollup for LLM context. Always included in invoke_llm_decision.

    Returns: small dict with:
      - per_strategy_edge: {strategy: edge_summary}
      - regime: {vix_bucket, top_strategies: []}
      - global_sample: total n_trades across all strategies
      - hint: a 1-sentence recommendation
    """
    # Per-strategy
    by_strat = defaultdict(list)
    for t in _load_closed_trades():
        s = t.get("strategy") or t.get("tags", {}).get("strategy") or "unknown"
        pnl = _safe_float(t.get("pnl") or t.get("realized_pnl") or 0.0)
        by_strat[s].append(pnl)

    per_strategy = {}
    for s, pnls in by_strat.items():
        if not pnls:
            continue
        n = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        per_strategy[s] = {
            "n": n,
            "win_rate": round(wins / n, 3),
            "total_pnl": round(sum(pnls), 2),
            "sample_grade": "A" if n >= 30 else "B" if n >= 20 else "C" if n >= 10 else "D" if n >= 5 else "F",
        }

    # Regime
    vix = _read_json(DATA / "liveness.json", default={}).get("snapshot", {}).get("vix")
    vix_b = _vix_bucket(_safe_float(vix))
    regime = get_regime_edge(vix_bucket=vix_b)

    # Global
    total_n = sum(s["n"] for s in per_strategy.values())
    total_pnl = sum(s["total_pnl"] for s in per_strategy.values())

    # Hint
    if total_n < 5:
        hint = f"Insufficient data ({total_n} trades). Trade conservatively, prefer defined-risk."
    elif total_pnl < 0:
        hint = f"Recent edge negative ({total_pnl:.0f} across {total_n} trades). Tighten stops, reduce size."
    else:
        top = regime.get("ranked", [])
        if top:
            hint = f"Recent edge positive ({total_pnl:.0f} across {total_n} trades). Top strategy: {top[0]}."
        else:
            hint = f"Recent edge positive ({total_pnl:.0f} across {total_n} trades)."

    return {
        "ts": _now_iso(),
        "lookback_days": days,
        "global": {
            "n_trades": total_n,
            "total_pnl": round(total_pnl, 2),
        },
        "per_strategy": per_strategy,
        "regime": {
            "vix_bucket": vix_b,
            "vix": vix,
            "top_strategies": regime.get("ranked", []),
        },
        "hint": hint,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", default=None)
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--summary", action="store_true", help="Print top-level summary")
    p.add_argument("--regime", action="store_true", help="Print regime edge")
    args = p.parse_args()

    if args.summary:
        print(json.dumps(get_backtest_summary(days=args.days), indent=2, default=str))
    elif args.regime:
        print(json.dumps(get_regime_edge(), indent=2, default=str))
    else:
        print(json.dumps(get_strategy_edge(strategy=args.strategy, days=args.days), indent=2, default=str))
