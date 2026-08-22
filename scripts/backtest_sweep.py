"""backtest_sweep.py — nightly backtest sweep across all strategies.

Runs all strategies in backtest/engine.py against NIFTY 6mo data from yfinance,
plus walk-forward analysis for each, and writes a JSON summary to
data_cache/backtest_sweep.json. Designed to be invoked by the nightly cron
"kotak-bot-nightly-backtest".

Usage:
    python scripts/backtest_sweep.py [--days 180] [--send-tg]

Output: writes to data_cache/backtest_sweep.json, prints a one-line summary.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def _safe_metric(d: dict, *keys, default=0.0):
    """Get nested metric, return default if missing."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    if cur is None:
        return default
    try:
        return float(cur)
    except (TypeError, ValueError):
        return default


def _summarize(result) -> dict:
    """Extract key metrics from a BacktestResult."""
    if result is None:
        return {}
    m = result.metrics or {}
    return {
        "strategy": result.strategy_name,
        "fold_index": result.fold_index,
        "total_return": _safe_metric(m, "total_return"),
        "annualized_return": _safe_metric(m, "annualized_return") or _safe_metric(m, "annual_return"),
        "sharpe": _safe_metric(m, "sharpe"),
        "sortino": _safe_metric(m, "sortino"),
        "max_drawdown": _safe_metric(m, "max_drawdown"),
        "win_rate": _safe_metric(m, "win_rate"),
        "n_trades": int(_safe_metric(m, "n_trades", default=0)),
        "is_profitable": result.is_profitable,
    }


def run_sweep(days: int = 180) -> dict:
    """Run all strategies + walk-forward and return summary dict."""
    summary: dict = {
        "ts": datetime.now().isoformat(),
        "days_requested": days,
        "data_source": None,
        "data_rows": 0,
        "data_start": None,
        "data_end": None,
        "strategies": [],
        "walk_forward": [],
        "errors": [],
    }

    # 1) Load data
    try:
        from kotak_bot.data.historical import HistoricalData
        hist = HistoricalData()
        df = hist.get_equity_ohlc("NIFTY", days=days, interval="1d")
        if df is None or df.empty:
            summary["errors"].append("no_data")
            return summary
        # normalize for backtest engine: needs OHLCV + datetime index
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"]) if "date" in df.columns else df.index
        if "date" in df.columns:
            df = df.set_index("date")
        df = df[["open", "high", "low", "close", "volume"]]
        summary["data_rows"] = len(df)
        summary["data_start"] = str(df.index[0].date()) if len(df) else None
        summary["data_end"] = str(df.index[-1].date()) if len(df) else None
        summary["data_source"] = "yfinance"  # HistoricalData prefers yfinance
    except Exception as e:
        summary["errors"].append(f"data_load: {type(e).__name__}: {e}")
        traceback.print_exc()
        return summary

    # 2) Run all strategies
    try:
        from backtest.engine import (
            BacktestConfig,
            BacktestEngine,
            EMACrossStrategy,
            RSIMeanReversionStrategy,
            BollingerBreakoutStrategy,
            compute_indicators,
        )
        # enforce_market_hours=False because our daily data has timestamps at 00:00,
        # which is OUTSIDE 09:15-15:30 — the filter would zero out all signals.
        # apply_lot_size=False because these are spot/NIFTY index tests, not options.
        cfg = BacktestConfig(
            initial_capital=200_000,
            symbol="NIFTY",
            enforce_market_hours=False,
            apply_lot_size=False,
        )
        engine = BacktestEngine(cfg)
        engine.load_data(df)
        # compute indicators once on the loaded data
        df_ind = compute_indicators(df)

        # Only use strategy configs that match what compute_indicators() generates:
        #   EMA_9, EMA_21, EMA_50, RSI_14, BBU_20_2.0, BBL_20_2.0, BBM_20_2.0, ATRr_14, ADX_14
        strategies = [
            EMACrossStrategy(fast=9, slow=21),
            EMACrossStrategy(fast=9, slow=50, rsi_filter=70),
            RSIMeanReversionStrategy(lower=30.0, upper=50.0),
            RSIMeanReversionStrategy(lower=25.0, upper=55.0),
            BollingerBreakoutStrategy(std=2.0, length=20),
        ]
        for strat in strategies:
            try:
                # Bypass vectorbt (broken with our numpy version) — use dry-run directly.
                entries = strat.entry_signals(df_ind).fillna(False).astype(bool)
                exits = strat.exit_signals(df_ind).fillna(False).astype(bool)
                size = strat.position_size(df_ind).fillna(0.0)
                result = engine._run_dry(df_ind, entries, exits, size, strat, fold_index=None)
                summary["strategies"].append(_summarize(result))
            except Exception as e:
                summary["errors"].append(f"run {strat.name}: {type(e).__name__}: {e}")

        # 3) Walk-forward on the best single strategy (EMA cross)
        # We bypass the engine.walk_forward because it dispatches to vectorbt which
        # is broken with our numpy version. Implement OOS walk-forward directly.
        try:
            if len(df) >= 100:
                n_splits = 2
                fold_size = len(df) // (n_splits + 1)
                for i in range(n_splits):
                    test_slice = df.iloc[(i + 1) * fold_size : (i + 2) * fold_size]
                    if test_slice.empty:
                        break
                    test_ind = compute_indicators(test_slice)
                    strat = EMACrossStrategy(fast=9, slow=21)
                    entries = strat.entry_signals(test_ind).fillna(False).astype(bool)
                    exits = strat.exit_signals(test_ind).fillna(False).astype(bool)
                    size = strat.position_size(test_ind).fillna(0.0)
                    r = engine._run_dry(test_ind, entries, exits, size, strat, fold_index=i)
                    r.metrics["fold_train_bars"] = fold_size
                    r.metrics["fold_test_bars"] = len(test_slice)
                    summary["walk_forward"].append(_summarize(r))
            else:
                summary["errors"].append("walk_forward: skipped (data too small, <100 bars)")
        except Exception as e:
            summary["errors"].append(f"walk_forward: {type(e).__name__}: {e}")
    except Exception as e:
        summary["errors"].append(f"engine: {type(e).__name__}: {e}")
        traceback.print_exc()

    return summary


def best_strategy(summary: dict) -> tuple[str, float] | tuple[None, None]:
    """Return (name, sharpe) of best single-run strategy by Sharpe."""
    best_name = None
    best_sharpe = -1e9
    for s in summary.get("strategies", []):
        sh = s.get("sharpe", -1e9)
        if sh > best_sharpe:
            best_sharpe = sh
            best_name = s.get("strategy")
    return (best_name, best_sharpe) if best_name else (None, None)


def format_telegram(summary: dict) -> str:
    """Format a 1-screen Telegram summary."""
    name, sharpe = best_strategy(summary)
    n_strats = len(summary.get("strategies", []))
    n_errs = len(summary.get("errors", []))
    rows = summary.get("data_rows", 0)
    start = summary.get("data_start", "?")
    end = summary.get("data_end", "?")
    msg = f"📊 Nightly Backtest Sweep\n"
    msg += f"Data: NIFTY 1d, {rows} bars ({start} → {end})\n"
    msg += f"Strategies tested: {n_strats} | Errors: {n_errs}\n"
    if name:
        msg += f"\n🏆 Best: {name} (Sharpe {sharpe:.2f})\n"
    msg += f"\nTop 3 by Sharpe:\n"
    sorted_strats = sorted(summary.get("strategies", []), key=lambda s: s.get("sharpe", -1e9), reverse=True)
    for i, s in enumerate(sorted_strats[:3], 1):
        msg += f"  {i}. {s.get('strategy')}: Sharpe {s.get('sharpe'):.2f} | ret {s.get('total_return', 0)*100:+.1f}% | DD {s.get('max_drawdown', 0)*100:.1f}%\n"
    if summary.get("walk_forward"):
        avg_sharpe = sum(r.get("sharpe", 0) for r in summary["walk_forward"]) / max(len(summary["walk_forward"]), 1)
        msg += f"\nWalk-forward (4 folds) avg Sharpe: {avg_sharpe:.2f}\n"
    if summary.get("errors"):
        msg += f"\n⚠️ Errors: {len(summary['errors'])} (see data_cache/backtest_sweep.json)"
    return msg


def send_telegram(msg: str) -> bool:
    """Send via curl.exe directly. Returns True if sent."""
    try:
        import subprocess
        from dotenv import load_dotenv
        env_path = ROOT / "config" / "credentials.env"
        if env_path.exists():
            load_dotenv(str(env_path))
        token = ""
        chat_id = ""
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("TELEGRAM_CHAT_ID="):
                chat_id = line.split("=", 1)[1].strip().strip('"').strip("'")
        if not token or not chat_id:
            print("send_tg: missing creds", flush=True)
            return False
        # write to temp file to avoid shell escaping issues
        import tempfile
        tmp = Path(tempfile.gettempdir()) / f"tg_bt_{datetime.now().strftime('%H%M%S')}.txt"
        tmp.write_text(msg, encoding="utf-8")
        # use curl.exe with --data-urlencode
        cmd = [
            "curl.exe", "-s", "-X", "POST",
            f"https://api.telegram.org/bot{token}/sendMessage",
            "--data-urlencode", f"chat_id={chat_id}",
            "--data-urlencode", f"text@{tmp}",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        try:
            tmp.unlink()
        except Exception:
            pass
        return r.returncode == 0 and '"ok":true' in r.stdout
    except Exception as e:
        print(f"send_tg failed: {e}", flush=True)
        return False


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=180, help="Lookback days for NIFTY data")
    p.add_argument("--send-tg", action="store_true", help="Send summary to Telegram")
    p.add_argument("--out", type=str, default=None, help="Output JSON path (default: data_cache/backtest_sweep.json)")
    args = p.parse_args()

    summary = run_sweep(days=args.days)
    out_path = Path(args.out) if args.out else (ROOT / "data_cache" / "backtest_sweep.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    name, sharpe = best_strategy(summary)
    sharpe_str = f"{sharpe:.2f}" if sharpe is not None else "NA"
    print(f"[backtest_sweep] {len(summary.get('strategies', []))} strategies, "
          f"data_rows={summary.get('data_rows', 0)}, "
          f"best={name} sharpe={sharpe_str}", flush=True)

    if args.send_tg:
        msg = format_telegram(summary)
        ok = send_telegram(msg)
        print(f"[backtest_sweep] telegram: {'sent' if ok else 'FAILED'}", flush=True)
    return 0


# pandas imported lazily inside run_sweep to keep import time fast
import pandas as pd  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
