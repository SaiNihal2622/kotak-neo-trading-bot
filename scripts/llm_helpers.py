"""LLM helper tools — the 'tools' the brain can call before deciding a trade.

Each helper does ONE thing well and returns a dict the LLM can read.
The brain pre-computes relevant helpers and includes them in the LLM
context, so the LLM gets empirical evidence + decision support without
having to ask for it.

Helpers:
  - select_strike_for_delta: pick the right strike for a given delta
  - validate_position: check if (entry, stop, qty) fits 1% risk budget
  - find_similar_setups: historical analogs with outcomes
  - pre_mortem: top failure modes for a candidate trade
  - workflow_log: persistent record of multi-step decisions
"""
from __future__ import annotations
import json
import os
import sys
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'
sys.path.insert(0, str(ROOT / "scripts"))

# --- Position validator ---

def validate_position(entry: float, stop: float, qty: int, capital: float = 100000) -> dict:
    """Check if a position's max loss fits the 1% risk budget.

    Returns a SCALED qty if the proposed qty would exceed 1% — never
    just "ok: false". Only REJECT if even 1 share would exceed 1% (i.e.
    the per-share loss is wider than 1% of capital, which means the
    stop is too far from entry — caller should pick a tighter stop).

    Returns: { ok, max_loss, max_loss_pct, max_loss_budget, headroom_pct,
              suggested_qty, scaled_from, reason }
    """
    if entry <= 0 or stop <= 0 or qty <= 0:
        return {"ok": False, "reason": "invalid inputs (entry/stop/qty must be > 0)"}
    if stop >= entry:
        return {"ok": False, "reason": f"stop ({stop}) must be below entry ({entry}) for long positions"}
    # Per-share loss
    loss_per_share = entry - stop
    max_loss = loss_per_share * qty
    max_loss_pct = max_loss / capital * 100
    # Per-share loss as % of capital
    per_share_pct = (loss_per_share / capital) * 100
    # If even 1 share exceeds 1% of capital, the strategy itself is too wide
    if per_share_pct > 1.0:
        return {
            "ok": False,
            "max_loss": max_loss,
            "max_loss_pct": round(max_loss_pct, 3),
            "max_loss_budget": capital * 0.01,
            "reason": f"per-share loss ₹{loss_per_share:,.2f} = {per_share_pct:.3f}% of capital > 1% — even 1 share is too wide; tighten stop",
        }
    # Scale qty down to fit 1% budget
    budget_shares = int((capital * 0.01) / loss_per_share)
    if budget_shares < 1:
        budget_shares = 1
    if budget_shares < qty:
        scaled = budget_shares
    else:
        scaled = qty
    scaled_loss = loss_per_share * scaled
    scaled_loss_pct = (scaled_loss / capital) * 100
    return {
        "ok": True,
        "max_loss": round(scaled_loss, 2),
        "max_loss_pct": round(scaled_loss_pct, 3),
        "max_loss_budget": capital * 0.01,
        "headroom_pct": round(1.0 - scaled_loss_pct, 3),
        "suggested_qty": scaled,
        "scaled_from": qty if scaled != qty else None,
        "reason": (
            "within 1% budget" if scaled == qty
            else f"scaled from {qty} to {scaled} shares to fit 1% budget (per-share loss ₹{loss_per_share:,.2f})"
        ),
    }


# --- Strike selector ---

def select_strike_for_delta(spot: float, target_delta: float, opt_type: str = "PE",
                            iv: float = 0.12, dte_days: int = 1) -> dict:
    """Pick the strike closest to a target delta using simple Black-Scholes math.
    Returns: { best: {strike, delta, premium}, alternatives, spot, target_delta }"""
    import math
    if opt_type.upper() not in ("CE", "PE"):
        return {"error": "opt_type must be CE or PE"}
    # Strike step: NIFTY 50, BANKNIFTY 100, FINNIFTY 50, MIDCPNIFTY 25, SENSEX 100
    step = 50
    if spot > 50000:
        step = 100
    elif spot > 20000:
        step = 50
    else:
        step = 25
    atm = round(spot / step) * step
    T = max(dte_days / 365.0, 0.001)
    sigma = max(iv, 0.05)  # floor at 5% to avoid blowups
    r = 0.06  # risk-free rate for India
    candidates = []
    for offset in range(-15, 16):
        K = atm + offset * step
        if K <= 0:
            continue
        # Black-Scholes d1
        d1 = (math.log(spot / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        # Standard normal CDF via error function approximation (no scipy dep)
        def N(x):
            return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
        nd1 = N(d1)
        nd2 = N(d2)
        if opt_type.upper() == "CE":
            delta = nd1
            # Call price = S*N(d1) - K*exp(-rT)*N(d2)
            premium = spot * nd1 - K * math.exp(-r * T) * nd2
        else:
            delta = nd1 - 1.0
            # Put price = K*exp(-rT)*N(-d2) - S*N(-d1)
            premium = K * math.exp(-r * T) * (1.0 - nd2) - spot * (1.0 - nd1)
        candidates.append({
            "strike": int(K),
            "delta": round(delta, 3),
            "premium_estimate": round(max(premium, 0.5), 2),
        })
    # For PE we look at absolute delta
    target_delta = abs(target_delta) if opt_type.upper() == "PE" else target_delta
    candidates.sort(key=lambda c: abs(abs(c["delta"]) - target_delta))
    return {
        "best": candidates[0] if candidates else None,
        "alternatives": candidates[1:4],
        "spot": spot,
        "target_delta": target_delta,
        "step": step,
        "note": "delta is signed: CE=positive, PE=negative. Premium is rough estimate; live chain has bid-ask spread.",
    }


# --- Similar setups finder ---

def find_similar_setups(strategy: str = None, regime: str = None, vol_regime: str = None,
                         n: int = 5) -> dict:
    """Look at past decisions and find ones with similar characteristics.
    Returns: { similar_count, avg_pnl, win_rate, examples: [...] }"""
    try:
        trades_path = DATA / "trades_state.json"
        if not trades_path.exists():
            return {"similar_count": 0, "note": "no trade history"}
        d = json.loads(trades_path.read_text(encoding="utf-8"))
        trades = d.get("trades", {}) or {}
        # Filter
        similar = []
        for tid, t in trades.items():
            plan = t.get("plan", {}) or {}
            if strategy and plan.get("strategy") != strategy:
                continue
            if regime and t.get("regime") != regime:
                continue
            similar.append({
                "trade_id": tid,
                "underlying": t.get("underlying"),
                "strategy": plan.get("strategy"),
                "pnl": t.get("realized_pnl", 0) or 0,
                "opened": t.get("opened_at", "")[:10],
                "rationale": (plan.get("reason", "") or "")[:120],
            })
        # Sort by P&L (best first)
        similar.sort(key=lambda x: x.get("pnl", 0), reverse=True)
        wins = sum(1 for s in similar if s.get("pnl", 0) > 100)
        losses = sum(1 for s in similar if s.get("pnl", 0) < -100)
        similar = similar[:n]
        return {
            "filter": {"strategy": strategy, "regime": regime, "vol_regime": vol_regime},
            "similar_count": len(similar),
            "win_count": wins,
            "loss_count": losses,
            "avg_pnl": round(sum(s.get("pnl", 0) for s in similar) / max(len(similar), 1), 2),
            "examples": similar,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


# --- Pre-mortem helper ---

def pre_mortem(strategy: str, context: dict) -> dict:
    """Top failure modes for a candidate strategy given current context.
    Returns: { top_risks: [...], mitigations: [...] }"""
    risks = []
    mitigations = []
    vix = (context.get("liveness") or {}).get("snapshot", {}).get("vix", 0) or 0
    if vix > 15:
        risks.append(f"VIX elevated ({vix:.1f}) — option premiums are richer but vol can spike further on news")
        mitigations.append("use ATM straddle to capture vol expansion (works both directions)")
    elif vix < 11:
        risks.append(f"VIX very low ({vix:.1f}) — selling premium is attractive but mean-reversion to 13-15 will crush shorts")
        mitigations.append("avoid naked short premium; use defined-risk spreads (iron condor with wings)")
    if strategy in ("long_call", "long_put"):
        risks.append("theta decay accelerates as expiry approaches — if the move doesn't come, premium melts")
        mitigations.append("use weekly expiry with max 1-2 day hold; exit if no move in 30 min")
    if strategy in ("iron_condor", "short_strangle", "short_straddle"):
        risks.append("tail risk on gap-up or gap-down outside the wings — max loss = wing width")
        mitigations.append("set max-loss stop at 1.5x the credit collected, close immediately if breached")
    if strategy in ("bull_call_vertical", "bear_put_vertical"):
        risks.append("directional move doesn't materialize — both legs decay")
        mitigations.append("close at 50% of max profit OR if underlying moves against by 30% of strike width")
    # Open positions risk
    n_open = len((context.get("paper") or {}).get("positions", {}) or {})
    if n_open >= 4:
        risks.append(f"Already {n_open} open positions — adding more dilutes risk per position")
        mitigations.append("close weakest position first before opening new one")
    elif n_open >= 2:
        risks.append(f"{n_open} open positions — running low on risk budget")
        mitigations.append("consider correlation: are these positions all in the same direction?")
    return {"top_risks": risks[:4], "mitigations": mitigations[:4]}


# --- Workflow log ---

WORKFLOW_LOG_PATH = DATA / "workflow_log.jsonl"
_WORKFLOW_HISTORY: deque = deque(maxlen=100)


def log_workflow(workflow: str, step: str, content: dict) -> None:
    """Log a workflow step for visibility and audit."""
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "workflow": workflow,
        "step": step,
        "content": content,
    }
    _WORKFLOW_HISTORY.append(entry)
    try:
        with WORKFLOW_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass


def get_workflow_log(n: int = 20) -> list:
    """Read last N workflow log entries."""
    if not WORKFLOW_LOG_PATH.exists():
        return []
    try:
        lines = WORKFLOW_LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()[-n:]
        return [json.loads(l) for l in lines if l.strip()]
    except Exception:
        return []


# --- Pre-market workflow ---

def run_morning_brief() -> dict:
    """Pre-market workflow: pull global state, overnight analysis, prepare for open.
    Multi-step: read state, scan news, build morning thesis, log to workflow log."""
    log_workflow("morning_brief", "start", {})
    # Step 1: Read global state
    try:
        global_state = json.loads((DATA / "global_state.json").read_text(encoding="utf-8"))
        log_workflow("morning_brief", "global_state_loaded", {
            "n_instruments": len(global_state.get("instruments", {})),
        })
    except Exception:
        global_state = {}
    # Step 2: Build morning thesis
    instruments = global_state.get("instruments", {})
    us_vix = instruments.get("^VIX", {}).get("pct_1d", 0)
    us_spx = instruments.get("^GSPC", {}).get("pct_1d", 0)
    asia_hsi = instruments.get("^HSI", {}).get("pct_1d", 0)
    thesis = {
        "us_overnight": {
            "spx_pct": us_spx,
            "vix_pct": us_vix,
            "interpretation": "risk-on" if us_spx > 0.5 and us_vix < -2 else
                              "risk-off" if us_spx < -0.5 and us_vix > 2 else
                              "neutral",
        },
        "asia_overnight": {
            "hsi_pct": asia_hsi,
            "interpretation": "weak Asia" if asia_hsi < -0.5 else
                              "strong Asia" if asia_hsi > 0.5 else "flat Asia",
        },
        "expected_nse_open": "gap-down" if (us_spx < -0.3 and asia_hsi < -0.3) else
                             "gap-up" if (us_spx > 0.3 and asia_hsi > 0.3) else
                             "flat-open, follow global cues intraday",
    }
    log_workflow("morning_brief", "thesis_built", thesis)
    return {"global_state_loaded": bool(instruments), "thesis": thesis, "instruments": len(instruments)}


def run_eod_review() -> dict:
    """End-of-day workflow: review trades, calculate P&L, plan tomorrow."""
    log_workflow("eod_review", "start", {})
    # Read paper state
    try:
        paper = json.loads((DATA / "paper_state.json").read_text(encoding="utf-8"))
    except Exception:
        paper = {}
    realized = paper.get("realized_pnl", 0) or 0
    cash = paper.get("cash", 0) or 0
    n_orders = len(paper.get("orders", []) or [])
    # Read today's decisions
    today = datetime.now().strftime("%Y-%m-%d")
    decisions = []
    try:
        brain_path = DATA / "quant_service_decisions.jsonl"
        for line in brain_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                d = json.loads(line)
                if d.get("ts", "").startswith(today):
                    decisions.append(d)
            except Exception:
                continue
    except Exception:
        pass
    review = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "date": today,
        "realized_pnl": realized,
        "cash": cash,
        "orders_today": n_orders,
        "llm_decisions_today": len(decisions),
        "opens": sum(1 for d in decisions if d.get("decision", {}).get("type") == "OPEN"),
        "holds": sum(1 for d in decisions if d.get("decision", {}).get("type") == "HOLD"),
        "closes": sum(1 for d in decisions if d.get("decision", {}).get("type") == "CLOSE"),
    }
    log_workflow("eod_review", "summary", review)
    return review


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "morning"
    if cmd == "morning":
        result = run_morning_brief()
        print(json.dumps(result, indent=2, default=str))
    elif cmd == "eod":
        result = run_eod_review()
        print(json.dumps(result, indent=2, default=str))
    elif cmd == "validate":
        # Example: BANKNIFTY 30-lot long put @ 150, stop 117
        print(json.dumps(validate_position(150, 117, 30, 100000), indent=2))
    elif cmd == "strike":
        # Example: NIFTY 24000 spot, target 30 delta PE
        print(json.dumps(select_strike_for_delta(24000, 0.30, "PE", 0.12, 1), indent=2))
    elif cmd == "similar":
        # Example: similar iron condors
        print(json.dumps(find_similar_setups(strategy="iron_condor", n=3), indent=2))
    elif cmd == "pre_mortem":
        # Example: pre-mortem for a long call
        ctx = {"liveness": {"snapshot": {"vix": 10.8}}, "paper": {"positions": {}}}
        print(json.dumps(pre_mortem("long_call", ctx), indent=2))
    elif cmd == "log":
        for entry in get_workflow_log(10):
            print(f"[{entry['ts']}] {entry['workflow']}/{entry['step']}")
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python llm_helpers.py [morning|eod|validate|strike|similar|pre_mortem|log]")
