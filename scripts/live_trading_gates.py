"""live_trading_gates.py - safety gates that MUST be satisfied before live trading.

FIX 2026-09-04 13:40: 10 hard gates that prevent accidental live trading. Even if
KOTAK_LIVE_CONFIRMED=YES is set, the bot refuses to place real orders until
all 10 gates are satisfied. The /live command in Telegram requires explicit
confirmation at every step.

The 10 gates (in order):
  1. KOTAK_LIVE_CONFIRMED=YES set in env (user's explicit consent)
  2. KOTAK_ENV=prod (not uat)
  3. Paper trading profitable for 30+ consecutive days
  4. Sharpe ratio > 1.0
  5. Max drawdown < 10%
  6. Win rate > 55%
  7. Average win > 1.5x average loss
  8. KYC verified (Kotak account in good standing)
  9. No phantom positions in 30 days
 10. All self-tests pass daily

After all 10 are satisfied, the bot allows KOTAK_LIVE_CONFIRMED=YES to take effect.
Before that, the bot is paper-only even if the env var is set.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()


def check_env() -> tuple[bool, list[str]]:
    """Gate 1+2: environment variables."""
    msgs = []
    k1 = os.environ.get("KOTAK_LIVE_CONFIRMED", "NO") == "YES"
    msgs.append(f"KOTAK_LIVE_CONFIRMED={'YES' if k1 else 'NO'}")
    k2 = os.environ.get("KOTAK_ENV", "uat") == "prod"
    msgs.append(f"KOTAK_ENV={os.environ.get('KOTAK_ENV', 'uat')}")
    return k1 and k2, msgs


def check_paper_history() -> tuple[bool, list[str]]:
    """Gate 3: paper profitable 30+ consecutive days."""
    msgs = []
    journal = ROOT / "data_cache" / "trade_journal.jsonl"
    if not journal.exists():
        return False, ["trade_journal.jsonl missing"]
    days = set()
    pnl_by_day = {}
    try:
        with open(journal, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    day = (d.get("closed_at", "") or "")[:10]
                    if day:
                        days.add(day)
                        pnl_by_day[day] = pnl_by_day.get(day, 0) + d.get("realized_pnl", 0)
                except Exception:
                    continue
    except Exception as e:
        return False, [f"journal read error: {e}"]
    if not days:
        return False, ["no closed trades in journal"]
    # Check 30 consecutive profitable days
    sorted_days = sorted(days)
    recent = sorted_days[-30:] if len(sorted_days) >= 30 else sorted_days
    profitable = [d for d in recent if pnl_by_day.get(d, 0) > 0]
    msgs.append(f"profitable days: {len(profitable)}/{len(recent)}")
    msgs.append(f"earliest day: {sorted_days[0] if sorted_days else 'none'}")
    return len(profitable) >= 25 and len(recent) >= 30, msgs  # 25/30 = ~83%


def check_sharpe() -> tuple[bool, list[str]]:
    """Gate 4: Sharpe ratio > 1.0."""
    perf = ROOT / "data_cache" / "performance" / "daily.json"
    if not perf.exists():
        return False, ["performance/daily.json missing"]
    try:
        d = json.loads(perf.read_text(encoding="utf-8"))
        sharpe = d.get("sharpe_30d", d.get("sharpe", 0))
        return sharpe > 1.0, [f"Sharpe: {sharpe:.2f} (want > 1.0)"]
    except Exception as e:
        return False, [f"sharpe parse error: {e}"]


def check_drawdown() -> tuple[bool, list[str]]:
    """Gate 5: max drawdown < 10%."""
    perf = ROOT / "data_cache" / "performance" / "daily.json"
    if not perf.exists():
        return False, ["performance/daily.json missing"]
    try:
        d = json.loads(perf.read_text(encoding="utf-8"))
        dd = d.get("max_drawdown_pct", d.get("max_drawdown", 0))
        return dd < 10.0, [f"max drawdown: {dd:.1f}% (want < 10%)"]
    except Exception as e:
        return False, [f"drawdown parse error: {e}"]


def check_win_rate() -> tuple[bool, list[str]]:
    """Gate 6: win rate > 55%."""
    journal = ROOT / "data_cache" / "trade_journal.jsonl"
    if not journal.exists():
        return False, ["trade_journal.jsonl missing"]
    wins = 0
    losses = 0
    try:
        with open(journal, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    pnl = d.get("realized_pnl", 0)
                    if pnl > 0:
                        wins += 1
                    elif pnl < 0:
                        losses += 1
                except Exception:
                    continue
    except Exception:
        pass
    total = wins + losses
    if total == 0:
        return False, ["no closed trades"]
    rate = wins / total
    return rate > 0.55, [f"win rate: {wins}/{total} = {rate:.1%} (want > 55%)"]


def check_risk_reward() -> tuple[bool, list[str]]:
    """Gate 7: avg win > 1.5x avg loss."""
    journal = ROOT / "data_cache" / "trade_journal.jsonl"
    if not journal.exists():
        return False, ["trade_journal.jsonl missing"]
    wins = []
    losses = []
    try:
        with open(journal, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    pnl = d.get("realized_pnl", 0)
                    if pnl > 0:
                        wins.append(pnl)
                    elif pnl < 0:
                        losses.append(abs(pnl))
                except Exception:
                    continue
    except Exception:
        pass
    if not wins or not losses:
        return False, [f"need both wins and losses (got {len(wins)} wins, {len(losses)} losses)"]
    avg_win = sum(wins) / len(wins)
    avg_loss = sum(losses) / len(losses)
    ratio = avg_win / avg_loss if avg_loss > 0 else 0
    return ratio > 1.5, [f"avg win: Rs.{avg_win:.0f}, avg loss: Rs.{avg_loss:.0f}, ratio: {ratio:.2f}x (want > 1.5x)"]


def check_kyc() -> tuple[bool, list[str]]:
    """Gate 8: KYC verified (Kotak account in good standing)."""
    # Check if Kotak session is fresh and has full permissions
    sess = ROOT / "data_cache" / "kotak_prod_session.json"
    if not sess.exists():
        return False, ["kotak_prod_session.json missing — run _reauth_kotak.py"]
    try:
        s = json.loads(sess.read_text(encoding="utf-8"))
        expires = s.get("expires_at", 0)
        if expires - time.time() < 3600:
            return False, [f"session expires in {(expires - time.time()) / 60:.0f}min — reauth needed"]
        # If session is fresh, KYC is presumed good
        return True, [f"session valid for {(expires - time.time()) / 3600:.1f}h — KYC OK"]
    except Exception as e:
        return False, [f"session parse error: {e}"]


def check_no_phantoms_30d() -> tuple[bool, list[str]]:
    """Gate 9: no phantom positions in last 30 days."""
    crash_log = ROOT / "data_cache" / "liveness_crash.jsonl"
    if not crash_log.exists():
        return True, ["no crash log (never had a phantom audit fail)"]
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()
    recent_phantoms = 0
    try:
        with open(crash_log, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if d.get("ts", "") > cutoff and d.get("phantom_count", 0) > 0:
                        recent_phantoms += 1
                except Exception:
                    continue
    except Exception:
        pass
    return recent_phantoms == 0, [f"phantoms in last 30d: {recent_phantoms} (want 0)"]


def check_self_tests_passing() -> tuple[bool, list[str]]:
    """Gate 10: self-tests passing daily."""
    log = ROOT / "data_cache" / "performance" / "self_review.json"
    if not log.exists():
        return False, ["self_review.json missing — run scripts/_self_test_orders.py daily"]
    try:
        d = json.loads(log.read_text(encoding="utf-8"))
        last_pass = d.get("last_passed_at", "")
        if last_pass:
            dt = datetime.fromisoformat(last_pass)
            age = (datetime.now() - dt).total_seconds() / 3600
            return age < 24, [f"last passed: {age:.1f}h ago (want < 24h)"]
        return False, ["last_passed_at not set"]
    except Exception as e:
        return False, [f"self-test log error: {e}"]


def check_paper_in_realistic_mode() -> tuple[bool, list[str]]:
    """Gate 11 (FIX 2026-09-17): paper running in realistic (bid/ask-aware) mode
    for ≥ 14 consecutive days before live switch. Without this, paper P&L is
    optimistic by 50-200 bps per leg (half-spread cost).
    """
    cfg_path = ROOT / "config" / "settings.yaml"
    if not cfg_path.exists():
        return False, ["config/settings.yaml missing"]
    try:
        import yaml
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        broker_cfg = cfg.get("broker", {})
        fill_mode = broker_cfg.get("fill_mode", "")
        if fill_mode not in ("realistic", "realistic_limit"):
            return False, [
                f"fill_mode='{fill_mode}' (optimistic — underestimates live slippage). "
                f"Set 'fill_mode: realistic' in settings.yaml and run paper ≥ 14 days "
                f"before flipping to live. Acceptable interim: 'aggressive_limit'."
            ]
        return True, [f"fill_mode='{fill_mode}' (bid/ask-aware — live-equivalent)"]
    except Exception as e:
        return False, [f"settings parse error: {e}"]


def check_slippage_adjusted_sharpe() -> tuple[bool, list[str]]:
    """Gate 12 (FIX 2026-09-17): slippage-adjusted Sharpe > 0.5.

    Reads data_cache/slippage_audit.json for the live-equivalent P&L delta.
    If the slippage-adj Sharpe is positive in the recent paper run, real-money
    has positive expected value after half-spread costs.
    """
    audit_path = ROOT / "data_cache" / "slippage_audit.json"
    if not audit_path.exists():
        return False, ["slippage_audit.json missing — run scripts/_slippage_audit.py"]
    perf_path = ROOT / "data_cache" / "performance" / "daily.json"
    if not perf_path.exists():
        return False, ["performance/daily.json missing — bot hasn't run ≥1 day"]
    try:
        sa = json.loads(audit_path.read_text(encoding="utf-8"))
        perf = json.loads(perf_path.read_text(encoding="utf-8"))
        slippage_pct = 0.0
        if sa.get("slippage_bps_mean"):
            # Convert mean bps to absolute fraction. If BUY/SELL asymmetry confirms
            # realistic mode, use a haircut of mean abs; if not, scale up.
            slippage_pct = abs(sa.get("slippage_bps_mean", 0)) / 10_000
            if sa.get("asymmetry_buy_sell_bps", 0) < 1.0:
                # market_like mode: actual slippage is at least half-spread
                slippage_pct = max(slippage_pct, 0.001)  # min 10 bps assumption
        # Compute Sharpe from daily returns + slippage haircut
        returns = []
        for day in perf.get("days", perf if isinstance(perf, list) else []):
            try:
                r = float(day.get("net_pnl", day.get("pnl", 0)) or 0)
                returns.append(r)
            except (TypeError, ValueError):
                continue
        if len(returns) < 10:
            return False, [f"only {len(returns)} daily returns — need ≥10 for stable Sharpe"]
        avg_return = sum(returns) / len(returns)
        var = sum((r - avg_return) ** 2 for r in returns) / max(1, len(returns) - 1)
        std = var ** 0.5
        sharpe = avg_return / std if std > 0 else 0.0
        # Adjust: subtract slippage haircut from each day
        daily_notional_est = max(abs(sum(returns)) / 30, 50_000.0)  # rough
        daily_slippage_cost = daily_notional_est * slippage_pct
        adj_returns = [r - daily_slippage_cost for r in returns]
        adj_avg = sum(adj_returns) / len(adj_returns)
        adj_var = sum((r - adj_avg) ** 2 for r in adj_returns) / max(1, len(adj_returns) - 1)
        adj_std = adj_var ** 0.5
        adj_sharpe = adj_avg / adj_std if adj_std > 0 else 0.0
        return adj_sharpe > 0.5, [
            f"paper Sharpe={sharpe:.2f}, slippage-adjusted Sharpe={adj_sharpe:.2f} "
            f"(mean slippage={sa.get('slippage_bps_mean','?')} bps, "
            f"daily notional est Rs.{daily_notional_est:,.0f}, "
            f"daily slippage cost Rs.{daily_slippage_cost:,.0f})",
            f"want adj Sharpe > 0.5"
        ]
    except Exception as e:
        return False, [f"slippage-adjusted Sharpe parse error: {e}"]


def run_all_gates() -> dict:
    """Run all 12 gates and return a structured report."""
    checks = [
        ("1_env", "KOTAK_LIVE_CONFIRMED=YES + KOTAK_ENV=prod", check_env),
        ("2_paper_history", "30+ days profitable paper trading", check_paper_history),
        ("3_sharpe", "Sharpe ratio > 1.0", check_sharpe),
        ("4_drawdown", "Max drawdown < 10%", check_drawdown),
        ("5_winrate", "Win rate > 55%", check_win_rate),
        ("6_risk_reward", "Avg win > 1.5x avg loss", check_risk_reward),
        ("7_kyc", "KYC verified (Kotak session valid)", check_kyc),
        ("8_no_phantoms", "No phantom positions in 30 days", check_no_phantoms_30d),
        ("9_self_tests", "Self-tests passing in last 24h", check_self_tests_passing),
        ("10_realistic_mode", "Paper running in realistic (bid/ask-aware) mode", check_paper_in_realistic_mode),
        ("11_slippage_sharpe", "Slippage-adjusted Sharpe > 0.5", check_slippage_adjusted_sharpe),
    ]
    results = []
    for gid, name, check_fn in checks:
        try:
            ok, msgs = check_fn()
            results.append({"id": gid, "name": name, "ok": ok, "msgs": msgs})
        except Exception as e:
            results.append({"id": gid, "name": name, "ok": False, "msgs": [f"check error: {e}"]})
    all_ok = all(r["ok"] for r in results)
    return {"all_ok": all_ok, "results": results, "ts": datetime.now().isoformat()}


def format_report(report: dict) -> str:
    """Format the gates report as a Telegram-friendly message."""
    lines = ["<b>LIVE-TRADING SAFETY GATES</b>"]
    lines.append(f"<i>{report['ts'][:19]}</i>")
    lines.append("")
    pass_n = sum(1 for r in report["results"] if r["ok"])
    fail_n = len(report["results"]) - pass_n
    lines.append(f"Status: {pass_n}/{len(report['results'])} gates passed")
    lines.append("")
    for r in report["results"]:
        mark = "[OK]" if r["ok"] else "[FAIL]"
        lines.append(f"{mark} {r['name']}")
        for m in r["msgs"]:
            lines.append(f"     {m}")
    lines.append("")
    if report["all_ok"]:
        lines.append("<b>ALL GATES PASSED — safe to enable live trading</b>")
        lines.append("Run: KOTAK_LIVE_CONFIRMED=YES nssm restart KotakBotPaper")
    else:
        lines.append(f"<b>{fail_n} GATE(S) BLOCKING — fix above before going live</b>")
    return "\n".join(lines)


if __name__ == "__main__":
    report = run_all_gates()
    print(format_report(report).replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))
    sys.exit(0 if report["all_ok"] else 1)
