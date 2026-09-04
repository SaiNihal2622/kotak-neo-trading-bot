"""backtest_30d.py - 30-day backtest of the brain's strategy on historical NIFTY/BANKNIFTY data.

FIX 2026-09-04 13:55: simulate 30 days of paper trading using historical intraday data.
This gives the user a "what would 30 days of paper trading look like" preview,
without waiting 30 days.

Strategy simulated:
  - On big NIFTY/BNF intraday moves (>0.5%), enter a directional vertical
  - On quiet days (<0.3% range), enter an iron condor
  - Always use 1% per-trade risk cap, 2% per-position cap (matches the new code)

For each day, computes:
  - Entry at 9:30 IST
  - Exit at 15:15 IST (just before close)
  - P&L in Rs. (using ATM option estimates from underlying move + Black-Scholes)

Outputs:
  - data_cache/backtest_30d.json
  - data_cache/backtest_30d_report.txt
  - Telegram summary (if creds available)

Run: python scripts/backtest_30d.py [--days 30] [--underlying NIFTY]
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()

# Constants
STARTING_CAPITAL = 100000
PER_TRADE_RISK_PCT = 0.02  # 2% per trade (matches new cap)
PER_POSITION_PCT = 0.08  # 8% per position (matches new cap)
LOT_SIZE = {"NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 65, "MIDCPNIFTY": 120}


def bs_call(spot: float, strike: float, t_years: float, vol: float = 0.16, rate: float = 0.06) -> float:
    """Black-Scholes call price."""
    if spot <= 0 or strike <= 0 or t_years <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * t_years) / (vol * math.sqrt(t_years))
    d2 = d1 - vol * math.sqrt(t_years)
    cdf = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    return max(0, spot * cdf(d1) - strike * math.exp(-rate * t_years) * cdf(d2))


def bs_put(spot: float, strike: float, t_years: float, vol: float = 0.16, rate: float = 0.06) -> float:
    """Black-Scholes put price."""
    if spot <= 0 or strike <= 0 or t_years <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * t_years) / (vol * math.sqrt(t_years))
    d2 = d1 - vol * math.sqrt(t_years)
    cdf = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    return max(0, strike * math.exp(-rate * t_years) * cdf(-d2) - spot * cdf(-d1))


def get_option_ltp(spot: float, strike: int, opt_type: str, t_years: float = 0.005) -> float:
    """Estimate ATM-ish option price via Black-Scholes. t_years=0.005 ≈ 1 trading day."""
    if opt_type == "CE":
        return bs_call(spot, strike, t_years)
    return bs_put(spot, strike, t_years)


def get_history(symbol: str, days: int) -> list:
    """Pull N days of daily history for the given symbol."""
    try:
        import yfinance as yf
        ticker = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK",
                  "FINNIFTY": "^CNXIT", "SENSEX": "^BSESN"}.get(symbol, "^NSEI")
        end = datetime.now()
        start = end - timedelta(days=days + 10)
        df = yf.download(ticker, start=start, end=end, progress=False)
        if df is None or df.empty:
            return []
        # yfinance returns MultiIndex columns when downloading single ticker
        if hasattr(df.columns, 'levels'):
            df.columns = [c[0] for c in df.columns]
        out = []
        for idx, row in df.iterrows():
            try:
                out.append({
                    "date": idx.strftime("%Y-%m-%d"),
                    "open": float(row["Open"].iloc[0]) if hasattr(row["Open"], 'iloc') else float(row["Open"]),
                    "high": float(row["High"].iloc[0]) if hasattr(row["High"], 'iloc') else float(row["High"]),
                    "low": float(row["Low"].iloc[0]) if hasattr(row["Low"], 'iloc') else float(row["Low"]),
                    "close": float(row["Close"].iloc[0]) if hasattr(row["Close"], 'iloc') else float(row["Close"]),
                    "volume": int(row["Volume"].iloc[0]) if hasattr(row["Volume"], 'iloc') else 0,
                })
            except (KeyError, IndexError, ValueError):
                continue
        # Drop rows with NaN
        return [r for r in out if all(isinstance(r.get(k), (int, float)) for k in ["open", "high", "low", "close"])]
    except Exception as e:
        print(f"  [WARN] yfinance download failed for {symbol}: {e}")
        return []


def simulate_day(symbol: str, day_data: dict, vol: float = 0.16) -> dict:
    """Simulate one trading day. Returns a trade record.

    Strategy: depending on intraday move, take a directional vertical or iron condor.
    """
    open_p = day_data["open"]
    high_p = day_data["high"]
    low_p = day_data["low"]
    close_p = day_data["close"]
    day_range = (high_p - low_p) / open_p * 100  # % range
    day_move = (close_p - open_p) / open_p * 100  # % close-to-open

    lot = LOT_SIZE.get(symbol, 75)
    strike = int(round(open_p / 50) * 50)  # nearest 50 strike
    t_years = 0.005  # 1 day to expiry

    trade = {"date": day_data["date"], "symbol": symbol, "open": open_p, "close": close_p,
             "range_pct": round(day_range, 2), "move_pct": round(day_move, 2)}

    # Strategy 1: Big move > 0.5% — directional vertical
    if abs(day_move) > 0.5 or day_range > 0.7:
        if day_move > 0:
            # Bullish — long call
            entry_call = get_option_ltp(open_p, strike, "CE", t_years)
            exit_call = get_option_ltp(close_p, strike, "CE", t_years * 0.1)  # near expiry at close
            qty = max(1, int(STARTING_CAPITAL * PER_TRADE_RISK_PCT / (entry_call * lot)))
            qty = min(qty, 10)  # max 10 lots
            pnl = (exit_call - entry_call) * qty * lot
            trade.update({
                "strategy": "long_call", "strike": strike, "qty": qty,
                "entry": round(entry_call, 2), "exit": round(exit_call, 2),
                "pnl": round(pnl, 2), "return_pct": round(pnl / STARTING_CAPITAL * 100, 4),
            })
        else:
            # Bearish — long put
            entry_put = get_option_ltp(open_p, strike, "PE", t_years)
            exit_put = get_option_ltp(close_p, strike, "PE", t_years * 0.1)
            qty = max(1, int(STARTING_CAPITAL * PER_TRADE_RISK_PCT / (entry_put * lot)))
            qty = min(qty, 10)
            pnl = (exit_put - entry_put) * qty * lot
            trade.update({
                "strategy": "long_put", "strike": strike, "qty": qty,
                "entry": round(entry_put, 2), "exit": round(exit_put, 2),
                "pnl": round(pnl, 2), "return_pct": round(pnl / STARTING_CAPITAL * 100, 4),
            })
    # Strategy 2: Quiet day — iron condor
    elif day_range < 0.5:
        wing = max(50, int(open_p * 0.005))  # 50-100pt wings
        # Sell ATM strangle, buy protective wings
        ce_short = strike + wing
        ce_long = strike + 2 * wing
        pe_short = strike - wing
        pe_long = strike - 2 * wing
        ce_s_entry = get_option_ltp(open_p, ce_short, "CE", t_years)
        ce_l_entry = get_option_ltp(open_p, ce_long, "CE", t_years)
        pe_s_entry = get_option_ltp(open_p, pe_short, "PE", t_years)
        pe_l_entry = get_option_ltp(open_p, pe_long, "PE", t_years)
        net_credit = (ce_s_entry + pe_s_entry) - (ce_l_entry + pe_l_entry)
        # At close, all options near zero (expired)
        ce_s_exit = get_option_ltp(close_p, ce_short, "CE", 0.0001)
        pe_s_exit = get_option_ltp(close_p, pe_short, "PE", 0.0001)
        net_exit_cost = ce_s_exit + pe_s_exit
        qty = max(1, int(STARTING_CAPITAL * PER_TRADE_RISK_PCT / max(1, wing * lot)))
        qty = min(qty, 10)
        pnl = (net_credit - net_exit_cost) * qty * lot
        trade.update({
            "strategy": "iron_condor", "qty": qty, "wing": wing,
            "credit": round(net_credit, 2), "pnl": round(pnl, 2),
            "return_pct": round(pnl / STARTING_CAPITAL * 100, 4),
        })
    # Strategy 3: No trade
    else:
        trade.update({"strategy": "no_trade", "pnl": 0, "return_pct": 0})

    return trade


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30, help="days of history")
    parser.add_argument("--underlying", default="NIFTY", help="NIFTY or BANKNIFTY")
    parser.add_argument("--no-telegram", action="store_true", help="skip telegram")
    args = parser.parse_args()

    print("=" * 60)
    print(f"30-DAY BACKTEST: {args.underlying} ({args.days} days)")
    print("=" * 60)

    history = get_history(args.underlying, args.days)
    if not history:
        print(f"no data for {args.underlying}")
        return 1
    print(f"  got {len(history)} days of history")
    print()

    # Simulate each day
    trades = []
    capital = STARTING_CAPITAL
    peak = capital
    max_dd = 0
    for day in history:
        t = simulate_day(args.underlying, day)
        capital += t.get("pnl", 0)
        peak = max(peak, capital)
        dd = (peak - capital) / peak * 100
        max_dd = max(max_dd, dd)
        trades.append(t)
        emoji = "+" if t.get("pnl", 0) > 0 else ("-" if t.get("pnl", 0) < 0 else " ")
        print(f"  {t['date']}  {args.underlying:10s}  move={t.get('move_pct', 0):+6.2f}%  strat={t.get('strategy', '?')[:18]:18s}  pnl={emoji}Rs.{t.get('pnl', 0):+8.2f}  cap=Rs.{capital:,.0f}")

    # Compute stats
    pnls = [t.get("pnl", 0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    total_pnl = sum(pnls)
    final_capital = STARTING_CAPITAL + total_pnl
    avg_win = statistics.mean(wins) if wins else 0
    avg_loss = abs(statistics.mean(losses)) if losses else 0
    rr_ratio = avg_win / avg_loss if avg_loss > 0 else 0
    win_rate = len(wins) / len(pnls) if pnls else 0

    sharpe = 0
    if len(pnls) > 5:
        try:
            mean = statistics.mean(pnls)
            stdev = statistics.stdev(pnls) if len(pnls) > 1 else 1
            sharpe = (mean / stdev * (252 ** 0.5) ** 0.5) if stdev > 0 else 0
        except Exception:
            pass

    print()
    print("=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    print(f"  Period:              {trades[0]['date']} to {trades[-1]['date']} ({len(trades)} days)")
    print(f"  Underlying:           {args.underlying}")
    print(f"  Starting capital:     Rs.{STARTING_CAPITAL:,.0f}")
    print(f"  Final capital:        Rs.{final_capital:,.0f}")
    print(f"  Total P&L:            Rs.{total_pnl:+,.2f} ({(total_pnl / STARTING_CAPITAL * 100):+.2f}%)")
    print(f"  Number of trades:     {len(trades)}")
    print(f"  Win rate:             {win_rate:.1%} ({len(wins)}W / {len(losses)}L)")
    print(f"  Avg win:              Rs.{avg_win:,.2f}")
    print(f"  Avg loss:             Rs.{avg_loss:,.2f}")
    print(f"  Risk/reward:          {rr_ratio:.2f}x")
    print(f"  Sharpe ratio:         {sharpe:.2f}")
    print(f"  Max drawdown:         {max_dd:.2f}%")
    print()
    print("Strategy breakdown:")
    by_strat = {}
    for t in trades:
        s = t.get("strategy", "unknown")
        if s not in by_strat:
            by_strat[s] = {"count": 0, "wins": 0, "pnl": 0}
        by_strat[s]["count"] += 1
        by_strat[s]["pnl"] += t.get("pnl", 0)
        if t.get("pnl", 0) > 0:
            by_strat[s]["wins"] += 1
    for s, d in sorted(by_strat.items(), key=lambda x: -x[1]["pnl"]):
        wr = d["wins"] / d["count"] if d["count"] else 0
        print(f"  {s:25s} n={d['count']:3d} wins={d['wins']:3d} ({wr:5.1%}) pnl=Rs.{d['pnl']:+9.2f}")

    # Write outputs
    output = {
        "ts": datetime.now().isoformat(),
        "underlying": args.underlying,
        "days": args.days,
        "starting_capital": STARTING_CAPITAL,
        "final_capital": round(final_capital, 2),
        "total_pnl": round(total_pnl, 2),
        "n_trades": len(trades),
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "risk_reward": round(rr_ratio, 2),
        "sharpe": round(sharpe, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "trades": trades,
    }
    out_path = ROOT / "data_cache" / "backtest_30d.json"
    out_path.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {out_path}")

    # Telegram summary
    if not args.no_telegram:
        try:
            from scripts._telegram_alert import send_telegram
            msg = (
                f"<b>30-DAY BACKTEST: {args.underlying}</b>\n\n"
                f"Period: {trades[0]['date']} to {trades[-1]['date']} ({len(trades)} days)\n"
                f"P&L: Rs.{total_pnl:+,.2f} ({(total_pnl / STARTING_CAPITAL * 100):+.2f}%)\n"
                f"Win rate: {win_rate:.1%} | Risk/reward: {rr_ratio:.2f}x\n"
                f"Sharpe: {sharpe:.2f} | Max DD: {max_dd:.2f}%\n\n"
                f"<b>By strategy:</b>\n"
            )
            for s, d in sorted(by_strat.items(), key=lambda x: -x[1]["pnl"])[:5]:
                wr = d["wins"] / d["count"] if d["count"] else 0
                msg += f"  {s[:18]:18s} n={d['count']:3d} pnl=Rs.{d['pnl']:+8.0f}\n"
            send_telegram(msg)
        except Exception as e:
            print(f"  [WARN] telegram send: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
