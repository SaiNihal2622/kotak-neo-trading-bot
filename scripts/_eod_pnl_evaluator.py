"""_eod_pnl_evaluator.py - evaluate today's trades at EOD using live option LTPs.

FIX 2026-09-04 13:55: at 15:30 IST, evaluate all open positions using the LAST live
option LTP from option_chains.json. Write actual outcomes to trade_journal.jsonl.
This gives realistic P&L that reflects what live trading would have produced.

Also computes the day's performance metrics and writes to performance/daily.json.

Run at 15:30 IST every day (or whenever EOD).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()


def get_live_ltp(symbol: str, strike: int, option_type: str) -> tuple:
    """Look up live LTP from option_chains.json. Returns (ltp, source)."""
    try:
        for cf in (ROOT / "data_cache").glob("option_chain_*.json"):
            try:
                cd = json.loads(cf.read_text(encoding="utf-8"))
                strikes = cd.get("strikes", {})
                key = f"{strike}_{option_type}" if strike and option_type else None
                if key and key in strikes:
                    return strikes[key].get("price", 0), "chain"
                for k, info in strikes.items():
                    if info.get("symbol") == symbol:
                        return info.get("price", 0), "chain"
            except Exception:
                continue
    except Exception:
        pass
    return 0, "none"


def get_spot(underlying: str) -> float:
    """Get current underlying spot from option_chains.json."""
    try:
        for cf in (ROOT / "data_cache").glob("option_chain_*.json"):
            try:
                cd = json.loads(cf.read_text(encoding="utf-8"))
                if cd.get("spot", 0) > 0:
                    return cd["spot"]
            except Exception:
                continue
    except Exception:
        pass
    return 0


def bs_estimate(spot: float, strike: int, option_type: str, t_years: float = 0.02) -> float:
    """Black-Scholes estimate. Used as last-resort fallback."""
    import math
    if spot <= 0 or strike <= 0 or t_years <= 0:
        return 0
    vol = 0.16
    rate = 0.06
    if option_type == "CE":
        intrinsic = max(0, spot - strike)
    else:
        intrinsic = max(0, strike - spot)
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * t_years) / (vol * math.sqrt(t_years))
    d2 = d1 - vol * math.sqrt(t_years)
    cdf = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    if option_type == "CE":
        price = spot * cdf(d1) - strike * math.exp(-rate * t_years) * cdf(d2)
    else:
        price = strike * math.exp(-rate * t_years) * cdf(-d2) - spot * cdf(-d1)
    return max(intrinsic, round(price, 2))


def evaluate_position(pos: dict) -> dict:
    """Evaluate a single open position at EOD. Returns realized P&L."""
    symbol = pos.get("symbol", "")
    underlying = pos.get("underlying", "")
    strike = int(pos.get("strike", 0))
    option_type = pos.get("option_type", "")
    qty = pos.get("qty", 0)
    avg = pos.get("avg_price", 0)

    # Try live LTP first
    exit_ltp, source = get_live_ltp(symbol, strike, option_type)
    if exit_ltp <= 0:
        # Fallback: B/S estimate
        spot = get_spot(underlying)
        exit_ltp = bs_estimate(spot, strike, option_type)
        source = "bs_estimate"

    if exit_ltp <= 0:
        return {"symbol": symbol, "exit_ltp": 0, "realized_pnl": 0, "source": "no_data"}

    # Compute realized P&L
    sign = 1 if pos.get("side", "BUY") == "SELL" else -1
    realized_pnl = (exit_ltp - avg) * qty * sign * -1  # close: opposite sign

    return {
        "symbol": symbol,
        "underlying": underlying,
        "strike": strike,
        "option_type": option_type,
        "qty": qty,
        "avg_price": avg,
        "exit_ltp": round(exit_ltp, 2),
        "realized_pnl": round(realized_pnl, 2),
        "source": source,
        "closed_at": datetime.now().isoformat(),
    }


def write_to_journal(evaluations: list, today: str):
    """Write evaluations to trade_journal.jsonl (append-only)."""
    journal_path = ROOT / "data_cache" / "trade_journal.jsonl"
    with open(journal_path, "a", encoding="utf-8") as f:
        for ev in evaluations:
            entry = {
                "trade_id": f"EOD-{today}-{ev['symbol'][:20]}",
                "symbol": ev["symbol"],
                "underlying": ev.get("underlying", ""),
                "strike": ev.get("strike", 0),
                "option_type": ev.get("option_type", ""),
                "qty": ev.get("qty", 0),
                "avg_price": ev.get("avg_price", 0),
                "exit_ltp": ev.get("exit_ltp", 0),
                "realized_pnl": ev.get("realized_pnl", 0),
                "exit_source": ev.get("source", ""),
                "closed_at": ev.get("closed_at", ""),
                "opened_at": today,
                "status": "closed_eod",
            }
            f.write(json.dumps(entry) + "\n")
    return len(evaluations)


def update_performance_metrics(evaluations: list, today: str):
    """Update performance/daily.json with today's metrics."""
    perf_path = ROOT / "data_cache" / "performance" / "daily.json"
    perf_path.parent.mkdir(parents=True, exist_ok=True)

    today_pnl = sum(e.get("realized_pnl", 0) for e in evaluations)
    wins = [e for e in evaluations if e.get("realized_pnl", 0) > 0]
    losses = [e for e in evaluations if e.get("realized_pnl", 0) < 0]
    n_trades = len(evaluations)
    win_rate = len(wins) / n_trades if n_trades else 0
    avg_win = sum(e["realized_pnl"] for e in wins) / len(wins) if wins else 0
    avg_loss = abs(sum(e["realized_pnl"] for e in losses) / len(losses)) if losses else 0
    rr_ratio = avg_win / avg_loss if avg_loss > 0 else 0

    # Load existing performance file
    if perf_path.exists():
        try:
            perf = json.loads(perf_path.read_text(encoding="utf-8"))
        except Exception:
            perf = {}
    else:
        perf = {}

    # Read all closed trades from journal to compute Sharpe
    journal_path = ROOT / "data_cache" / "trade_journal.jsonl"
    all_pnls = []
    if journal_path.exists():
        with open(journal_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    all_pnls.append(json.loads(line).get("realized_pnl", 0))
                except Exception:
                    continue

    sharpe = 0
    if len(all_pnls) > 5:
        import statistics
        try:
            mean = statistics.mean(all_pnls)
            stdev = statistics.stdev(all_pnls) if len(all_pnls) > 1 else 1
            sharpe = (mean / stdev * (252 ** 0.5)) if stdev > 0 else 0
        except Exception:
            pass

    max_dd = 0
    if all_pnls:
        cum = 0
        peak = 0
        for p in all_pnls:
            cum += p
            peak = max(peak, cum)
            dd = peak - cum
            max_dd = max(max_dd, dd)

    perf[today] = {
        "date": today,
        "realized_pnl": round(today_pnl, 2),
        "n_trades": n_trades,
        "n_wins": len(wins),
        "n_losses": len(losses),
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "risk_reward": round(rr_ratio, 2),
        "sharpe": round(sharpe, 2),
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd / 100000 * 100, 2) if max_dd else 0,
    }
    # Update top-level rollups
    perf["last_updated"] = datetime.now().isoformat()
    perf["sharpe_30d"] = round(sharpe, 2)
    perf["max_drawdown_pct"] = round(max_dd / 100000 * 100, 2) if max_dd else 0

    perf_path.write_text(json.dumps(perf, indent=2), encoding="utf-8")
    return perf


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    print("=" * 60)
    print(f"EOD P&L EVALUATOR — {today} {datetime.now().strftime('%H:%M:%S')} IST")
    print("=" * 60)
    print()

    # Load paper state
    ps_path = ROOT / "data_cache" / "paper_state.json"
    if not ps_path.exists():
        print("paper_state.json missing — nothing to evaluate")
        return 0
    ps = json.loads(ps_path.read_text(encoding="utf-8"))
    positions = ps.get("positions", {})
    if not positions:
        print("no open positions — nothing to evaluate")
        return 0

    print(f"evaluating {len(positions)} open positions at EOD...")
    print()

    evaluations = []
    for sym, pos in positions.items():
        ev = evaluate_position(pos)
        evaluations.append(ev)
        print(f"  {sym:35s} avg={ev.get('avg_price', 0):>7.2f}  exit={ev.get('exit_ltp', 0):>7.2f}  pnl=Rs.{ev.get('realized_pnl', 0):>+8.2f}  src={ev.get('source', '?')}")

    total_pnl = sum(e.get("realized_pnl", 0) for e in evaluations)
    print()
    print(f"total EOD P&L: Rs.{total_pnl:+.2f}")
    print()

    # Write to journal
    n_written = write_to_journal(evaluations, today)
    print(f"wrote {n_written} entries to trade_journal.jsonl")

    # Update performance metrics
    perf = update_performance_metrics(evaluations, today)
    print(f"updated performance/daily.json")
    print()
    print("metrics:")
    print(f"  trades: {perf.get(today, {}).get('n_trades', 0)}")
    print(f"  wins: {perf.get(today, {}).get('n_wins', 0)}")
    print(f"  losses: {perf.get(today, {}).get('n_losses', 0)}")
    print(f"  win_rate: {perf.get(today, {}).get('win_rate', 0):.1%}")
    print(f"  risk_reward: {perf.get(today, {}).get('risk_reward', 0):.2f}x")
    print(f"  sharpe_30d: {perf.get('sharpe_30d', 0):.2f}")
    print(f"  max_drawdown_pct: {perf.get('max_drawdown_pct', 0):.2f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
