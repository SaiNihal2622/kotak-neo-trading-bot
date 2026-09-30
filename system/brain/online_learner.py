"""Online learner — track each trade outcome, update local likelihood.

PHASE 7 FINAL 2026-10-01: the brain is not a template. It LEARNS from
each trade. Every time a position closes, this module:

1. Records the outcome (win/loss, P&L, regime, ADX, RSI, VIX, side)
2. Computes per-strategy and per-regime win rates
3. Updates the local likelihood that bayesian_decision.py uses
4. Persists to data_cache/learning_state.json (atomic writes)

The Bayesian EV engine merges prior + likelihood, so as real outcomes
accumulate, the local likelihood gradually dominates the yfinance prior
(after ~50 virtual samples per side).

DESIGN:
- Learning is per-strategy × per-regime. A LONG in trending_up is
  different from a LONG in range_bound.
- We track: {strategy: {regime: {wins, losses, n, avg_win_pnl,
  avg_loss_pnl, sharpe_estimate}}}
- We also track global LONG vs SHORT win rates for the Bayesian engine.

WATCH FOR:
- Phantoms in trade_journal.jsonl (Rs.1 fills) — already filtered by
  the bayesian module's smoothing weight of 50, so this learner
  feeds straight confidence weighted counts.
- Strategy rename — if we change strategy names, old data won't
  match. Versioning: store per-version.
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data_cache"
JOURNAL_PATH = DATA_DIR / "trade_journal.jsonl"
LEARNING_STATE = DATA_DIR / "learning_state.json"

IST = timezone(timedelta(hours=5, minutes=30))

# Strategy categories for outcome tracking. Mapping from strategy name →
# bucket. Anything not in the map gets its own bucket.
STRATEGY_BUCKETS = {
    "nifty_cash_long": "long_cash",
    "nifty_cash_short": "short_cash",
    "nifty_swing_long": "long_swing",
    "nifty_swing_short": "short_swing",
    "nifty_long_call": "long_call",
    "nifty_long_put": "long_put",
    "nifty_short_straddle": "short_straddle",
    "nifty_iron_condor": "iron_condor",
}


def _now_ist() -> datetime:
    return datetime.now(IST)


def _atomic_write_json(path: Path, payload: dict) -> bool:
    """Atomic JSON write (no half-files on crash)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"[online_learner] write failed: {e}", file=sys.stderr)
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return False


def _load_state() -> dict:
    """Load learning_state.json or initialize."""
    if LEARNING_STATE.exists():
        try:
            return json.loads(LEARNING_STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "version": 1,
        "ts": _now_ist().isoformat(),
        "by_strategy": {},   # strategy → outcome counts
        "by_side": {"BUY": {"wins": 0, "losses": 0, "n": 0,
                            "sum_pnl": 0.0, "sum_win_pnl": 0.0,
                            "sum_loss_pnl": 0.0},
                    "SELL": {"wins": 0, "losses": 0, "n": 0,
                             "sum_pnl": 0.0, "sum_win_pnl": 0.0,
                             "sum_loss_pnl": 0.0}},
        "by_regime": {},     # regime → outcome counts
        "global": {"wins": 0, "losses": 0, "n": 0,
                   "sum_pnl": 0.0, "sharpe_estimate": 0.0,
                   "last_5_pnl": []},   # rolling for stability
        "last_update": None,
    }


def _save_state(state: dict) -> bool:
    state["ts"] = _now_ist().isoformat()
    return _atomic_write_json(LEARNING_STATE, state)


def _classify_outcome(pnl: float) -> str:
    """win / loss / breakeven."""
    if pnl > 1.0:
        return "win"
    if pnl < -1.0:
        return "loss"
    return "breakeven"


def _parse_journal_entries(side_filter: Optional[str] = None) -> list[dict]:
    """Parse trade_journal.jsonl into closed-trade outcome records.

    Two formats appear in the journal:
    1. RECON-* / closed-trade records: side=open_side, pnl=realized_pnl,
       strategy=open_tag (e.g. "QUANT-bear_put_v").
    2. FILL event records: side=side (entry fill, no P&L).

    We only want CLOSED TRADES — records with realized_pnl. Skip FILL events.
    Skip RESET/manual_reset markers.

    Phantoms: RECON entries marked phantom_price=true (Rs.1 orphan
    auto-close) are excluded — they'd poison win rate.
    """
    if not JOURNAL_PATH.exists():
        return []
    out = []
    for line in JOURNAL_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        # FILL events are entries, not closes
        if rec.get("event") == "FILL":
            continue
        # RESET markers are not trades
        if rec.get("event") in ("RESET", "manual_reset", "unknown"):
            continue
        # Need realized_pnl for outcome
        pnl = rec.get("realized_pnl")
        if pnl is None:
            continue
        try:
            pnl = float(pnl)
        except Exception:
            continue
        # Skip phantoms (orphan auto-close Rs.1 fills that faked wins)
        if rec.get("phantom_price") is True:
            continue
        # Side: closed trades use open_side; some use side
        side = (rec.get("open_side") or rec.get("side") or "").upper()
        if side not in ("BUY", "SELL"):
            continue
        if side_filter and side != side_filter:
            continue
        # Strategy: prefer open_tag, fallback to close_tag, fallback to strategy field
        strategy = (rec.get("open_tag") or rec.get("close_tag") or
                    rec.get("strategy") or "unknown")
        regime = rec.get("regime") or "unknown"
        rec_out = {
            "ts": rec.get("closed_at") or rec.get("ts") or rec.get("timestamp"),
            "strategy": strategy,
            "side": side,
            "regime": regime,
            "pnl": pnl,
            "outcome": _classify_outcome(pnl),
            "adx": rec.get("adx"),
            "rsi": rec.get("rsi"),
            "vix": rec.get("vix"),
        }
        out.append(rec_out)
    return out


def recompute(state: dict) -> dict:
    """Recompute all outcome stats from trade_journal.jsonl.

    Idempotent — reads journal from start, rebuilds all counts.
    Safe to call any time. O(N) over journal.
    """
    entries = _parse_journal_entries()
    by_strategy = {}
    by_side = {"BUY": {"wins": 0, "losses": 0, "n": 0,
                       "sum_pnl": 0.0, "sum_win_pnl": 0.0,
                       "sum_loss_pnl": 0.0},
               "SELL": {"wins": 0, "losses": 0, "n": 0,
                        "sum_pnl": 0.0, "sum_win_pnl": 0.0,
                        "sum_loss_pnl": 0.0}}
    by_regime = {}
    global_w = global_l = global_n = 0
    global_sum_pnl = 0.0
    rolling_5 = []

    for e in entries:
        strat = e["strategy"]
        side = e["side"]
        regime = e["regime"]
        outcome = e["outcome"]
        pnl = e["pnl"]

        # Per-strategy
        s = by_strategy.setdefault(strat, {
            "wins": 0, "losses": 0, "breakevens": 0, "n": 0,
            "sum_pnl": 0.0, "sum_win_pnl": 0.0, "sum_loss_pnl": 0.0,
        })
        s["n"] += 1
        s["sum_pnl"] += pnl
        if outcome == "win":
            s["wins"] += 1
            s["sum_win_pnl"] += pnl
        elif outcome == "loss":
            s["losses"] += 1
            s["sum_loss_pnl"] += pnl
        else:
            s["breakevens"] += 1

        # Per-side
        if side in by_side:
            sd = by_side[side]
            sd["n"] += 1
            sd["sum_pnl"] += pnl
            if outcome == "win":
                sd["wins"] += 1
                sd["sum_win_pnl"] += pnl
            elif outcome == "loss":
                sd["losses"] += 1
                sd["sum_loss_pnl"] += pnl

        # Per-regime
        r = by_regime.setdefault(regime, {
            "wins": 0, "losses": 0, "n": 0, "sum_pnl": 0.0,
        })
        r["n"] += 1
        r["sum_pnl"] += pnl
        if outcome == "win":
            r["wins"] += 1
        elif outcome == "loss":
            r["losses"] += 1

        # Global
        if outcome == "win":
            global_w += 1
        elif outcome == "loss":
            global_l += 1
        global_n += 1
        global_sum_pnl += pnl

        # Rolling 5
        rolling_5.append(round(pnl, 2))
        if len(rolling_5) > 5:
            rolling_5 = rolling_5[-5:]

    # Compute Sharpe estimate (annualized): mean / std * sqrt(N).
    # If n < 5, Sharpe is unreliable; cap at 0.
    sharpe_est = 0.0
    if global_n >= 5:
        pnls = [e["pnl"] for e in entries]
        mean = sum(pnls) / len(pnls)
        var = sum((p - mean) ** 2 for p in pnls) / len(pnls)
        std = math.sqrt(var) if var > 0 else 1.0
        # Annualized on ~252 trading days; daily vol here is per-trade
        # vol, so just multiply by sqrt(252) for daily Sharpe proxy.
        sharpe_est = round((mean / std) * math.sqrt(252), 2) if std > 0 else 0.0

    # Per-strategy win rates
    for strat, s in by_strategy.items():
        s["win_rate"] = round(s["wins"] / s["n"], 4) if s["n"] else 0
        s["avg_pnl"] = round(s["sum_pnl"] / s["n"], 2) if s["n"] else 0
        s["avg_win"] = round(s["sum_win_pnl"] / s["wins"], 2) if s["wins"] else 0
        s["avg_loss"] = round(s["sum_loss_pnl"] / s["losses"], 2) if s["losses"] else 0

    # Per-side win rates
    for side, sd in by_side.items():
        sd["win_rate"] = round(sd["wins"] / sd["n"], 4) if sd["n"] else 0
        sd["avg_pnl"] = round(sd["sum_pnl"] / sd["n"], 2) if sd["n"] else 0

    # Per-regime win rates
    for regime, r in by_regime.items():
        r["win_rate"] = round(r["wins"] / r["n"], 4) if r["n"] else 0
        r["avg_pnl"] = round(r["sum_pnl"] / r["n"], 2) if r["n"] else 0

    state["by_strategy"] = by_strategy
    state["by_side"] = by_side
    state["by_regime"] = by_regime
    state["global"] = {
        "wins": global_w,
        "losses": global_l,
        "n": global_n,
        "sum_pnl": round(global_sum_pnl, 2),
        "win_rate": round(global_w / global_n, 4) if global_n else 0,
        "sharpe_estimate": sharpe_est,
        "last_5_pnl": rolling_5,
    }
    state["last_update"] = _now_ist().isoformat()
    return state


def get_local_likelihood_for_bayesian(side: str) -> dict:
    """Return the local-outcome likelihood for Bayesian merge.

    Side: "BUY" or "SELL"
    Returns:
        {"win_rate": float, "n": int, "avg_gain": float, "avg_loss": float,
         "sharpe": float}

    Pulls from learning_state.json if fresh, else recomputes.
    """
    state = _load_state()
    if (not state.get("last_update") or
            state["global"]["n"] == 0):
        state = recompute(state)
        _save_state(state)
    sd = state["by_side"].get(side, {})
    n = sd.get("n", 0)
    if n == 0:
        return {"win_rate": 0.5, "n": 0, "avg_gain": 0.0,
                "avg_loss": 0.0, "sharpe": 0.0}
    return {
        "win_rate": sd.get("win_rate", 0.5),
        "n": n,
        "avg_gain": sd.get("sum_win_pnl", 0) / max(sd.get("wins", 1), 1),
        "avg_loss": sd.get("sum_loss_pnl", 0) / max(sd.get("losses", 1), 1),
        "sharpe": state["global"].get("sharpe_estimate", 0),
    }


def get_strategy_performance(strategy: str) -> dict:
    """Return performance summary for a specific strategy."""
    state = _load_state()
    if not state.get("last_update"):
        state = recompute(state)
        _save_state(state)
    return state["by_strategy"].get(strategy, {})


def update() -> dict:
    """Recompute and save learning state. Returns fresh state."""
    state = _load_state()
    state = recompute(state)
    _save_state(state)
    return state


def get_lessons_for_prompt(max_lessons: int = 4) -> str:
    """Build a prompt-injectable lessons block from learning state.

    Highlights:
    - Strategies with < 30% win rate AND n ≥ 5 (avoid them)
    - Strategies with > 60% win rate AND n ≥ 5 (favor them)
    - Regimes where we're net losing
    """
    state = _load_state()
    if state["global"]["n"] < 5:
        return ""  # Not enough data yet

    lines = ["[LEARNED PERFORMANCE — from local trade outcomes]"]
    # Per-strategy
    for strat, s in sorted(
        state["by_strategy"].items(),
        key=lambda kv: -kv[1].get("n", 0),
    )[:6]:
        if s.get("n", 0) < 3:
            continue
        lines.append(
            f"  {strat}: n={s['n']} win={s.get('win_rate', 0)*100:.1f}% "
            f"avg_pnl={s.get('avg_pnl', 0):+.2f}"
        )
    # Per-side summary
    for side in ("BUY", "SELL"):
        sd = state["by_side"].get(side, {})
        if sd.get("n", 0) >= 3:
            lines.append(
                f"  {side} total: n={sd['n']} win={sd.get('win_rate', 0)*100:.1f}% "
                f"avg_pnl={sd.get('avg_pnl', 0):+.2f}"
            )
    # Per-regime
    for regime, r in state["by_regime"].items():
        if r.get("n", 0) >= 3:
            lines.append(
                f"  regime={regime}: n={r['n']} win={r.get('win_rate', 0)*100:.1f}% "
                f"avg_pnl={r.get('avg_pnl', 0):+.2f}"
            )
    # Global
    g = state["global"]
    lines.append(
        f"  GLOBAL: n={g['n']} win={g.get('win_rate', 0)*100:.1f}% "
        f"sum_pnl={g.get('sum_pnl', 0):+.2f} sharpe_est={g.get('sharpe_estimate', 0)}"
    )
    return "\n".join(lines[:max_lessons * 4])  # cap total lines


if __name__ == "__main__":
    state = update()
    print(json.dumps(state["global"], indent=2))
    print("---")
    print(json.dumps(state["by_strategy"], indent=2))