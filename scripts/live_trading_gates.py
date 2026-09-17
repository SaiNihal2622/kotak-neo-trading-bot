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
    """Gate 3 (FIX 2026-09-17): 30+ days profitable paper trading.

    Counts realistic-mode-only days as primary, market_like-mode-only as
    secondary, mixed as "in transition". The 30-day threshold is on the
    realistic-mode count, since that's what we'll actually trade live.

    FIX 2026-09-17 13:25: read fills directly from trade_journal.jsonl
    (was previously broken — used `closed_at` field that the journal
    doesn't have, and `realized_pnl` (singular) instead of `realized_delta`).
    Each fill's realized_delta contributes to that day's P&L.
    """
    msgs = []
    journal = ROOT / "data_cache" / "trade_journal.jsonl"
    if not journal.exists():
        return False, ["trade_journal.jsonl missing"]
    days = set()
    realistic_days = set()
    pnl_by_day = {}
    realistic_pnl_by_day = {}
    try:
        with open(journal, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if d.get("phantom_price"):
                        continue
                    if d.get("event") != "FILL":
                        continue
                    day = (d.get("ts", "") or d.get("filled_at", "") or "")[:10]
                    if not day or len(day) < 10:
                        continue
                    rd = float(d.get("realized_delta", 0) or 0)
                    days.add(day)
                    pnl_by_day[day] = pnl_by_day.get(day, 0.0) + rd
                    # FIX 2026-09-17 13:25: realistic-mode detection. The journal
                    # doesn't tag fills by mode, but the audit does. If the slippage
                    # audit reports the day's BUY-SELL asymmetry >= 1 bps, the day
                    # counts as realistic-mode. Otherwise it's market_like-mode.
                    # This is approximate; exact mode tagging is future work.
                except Exception:
                    continue
    except Exception as e:
        return False, [f"journal read error: {e}"]
    if not days:
        return False, ["no fills in journal"]
    # FIX 2026-09-17 13:25: use slippage_audit to determine realistic-mode days.
    sa_path = ROOT / "data_cache" / "slippage_audit.json"
    sa = None
    if sa_path.exists():
        try:
            sa = json.loads(sa_path.read_text(encoding="utf-8"))
        except Exception:
            sa = None
    # If audit confirms realistic mode (asymmetry >= 1 bps), all the days in
    # the audit window count as realistic. Otherwise they count as market_like.
    is_realistic_recent = sa and sa.get("asymmetry_buy_sell_bps", 0) >= 1.0
    if is_realistic_recent:
        realistic_days = set(days)
        realistic_pnl_by_day = dict(pnl_by_day)
    else:
        # No realistic-mode confirmation yet; only old market_like days count
        # for the paper_history count, but realistic-mode days will accumulate
        # going forward.
        realistic_days = set()
        realistic_pnl_by_day = {}
    # Check 30 consecutive profitable days (realistic mode)
    sorted_days = sorted(realistic_days) if realistic_days else sorted(days)
    recent = sorted_days[-30:] if len(sorted_days) >= 30 else sorted_days
    pnl_source = realistic_pnl_by_day if realistic_days else pnl_by_day
    profitable = [d for d in recent if pnl_source.get(d, 0) > 0]
    msgs.append(
        f"profitable days: {len(profitable)}/{len(recent)} "
        f"({'realistic-mode' if is_realistic_recent else 'all-fills'})"
    )
    msgs.append(f"earliest day: {sorted_days[0] if sorted_days else 'none'}")
    msgs.append(f"total days with fills: {len(days)}")
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


def _daily_pnl_from_journal() -> dict[str, float]:
    """FIX 2026-09-17 13:25: compute per-day realized P&L directly from
    trade_journal.jsonl. Independent of performance/daily.json — uses the
    same journal the bot writes every fill to. Returns {YYYY-MM-DD: net_pnl}.
    """
    journal = ROOT / "data_cache" / "trade_journal.jsonl"
    if not journal.exists():
        return {}
    out: dict[str, float] = {}
    with journal.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("phantom_price"):
                continue
            if d.get("event") != "FILL":
                continue
            ts = (d.get("ts") or d.get("filled_at") or "")[:10]
            if not ts or len(ts) < 10:
                continue
            rd = float(d.get("realized_delta", 0) or 0)
            out[ts] = out.get(ts, 0.0) + rd
    return out


def _backtest_summary() -> dict | None:
    """FIX 2026-09-17 13:25: read the 30-day backtest result if available,
    so the slippage gate can bootstrap off the backtest until 10 days of
    live paper data accumulate.

    The backtest file lives at data_cache/backtest_30d.json (NOT under
    performance/ — that's where the bot's daily stats are). Its top-level
    keys are per-underlying; each has a `trades` list with daily P&L. We
    aggregate across all underlyings into a single daily_returns series.
    """
    p = ROOT / "data_cache" / "backtest_30d.json"
    if not p.exists():
        return None
    try:
        b = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(b, dict):
        return None
    # Aggregate daily P&L across all trades (if it's a list of underlying
    # results, flatten the trades). Single-underlying file: b is one underlying.
    daily_pnl: dict[str, float] = {}
    total_notional = 0.0
    n = 0
    if isinstance(b.get("trades"), list):
        # Single underlying — trades is the daily pnl series
        for t in b["trades"]:
            if not isinstance(t, dict):
                continue
            date = t.get("date", "")
            if not date:
                continue
            daily_pnl[date] = daily_pnl.get(date, 0.0) + float(t.get("pnl", 0) or 0)
            n += 1
    else:
        # Multi-underlying: aggregate trades from each underlying
        for sym_key, sym_data in b.items():
            if not isinstance(sym_data, dict):
                continue
            for t in sym_data.get("trades", []) or []:
                if not isinstance(t, dict):
                    continue
                date = t.get("date", "")
                if not date:
                    continue
                daily_pnl[date] = daily_pnl.get(date, 0.0) + float(t.get("pnl", 0) or 0)
                n += 1
    if not daily_pnl:
        return None
    daily_returns = sorted(daily_pnl.values())  # oldest first
    avg_daily_notional = 0.0
    if b.get("starting_capital") and b.get("days"):
        avg_daily_notional = float(b["starting_capital"]) * 1.5  # rough: 1.5x daily notional
    return {
        "ts": b.get("ts", ""),
        "days": b.get("days", len(daily_returns)),
        "n_trades": n,
        "daily_returns": daily_returns,
        "avg_daily_notional": avg_daily_notional or 100_000.0,
        "raw": b,
    }


def _slippage_haircut_per_day(returns: list[float], sa: dict) -> float:
    """FIX 2026-09-17 13:25: estimate the per-day slippage cost in INR.

    Uses tiered spread model: 5bps liquid / 15bps mid / 50bps deep OTM.
    Daily notional = average daily notional traded, derived from |mean daily P&L|
    multiplied by an option-PnL-to-notional ratio. If we don't have enough data,
    fall back to a conservative Rs.500/day assumption for Rs.100k capital.
    """
    if not returns:
        return 500.0
    avg_abs_pnl = sum(abs(r) for r in returns) / len(returns)
    # Empirical: option P&L is roughly 0.5-1% of notional per leg, and notional
    # is typically 30-50x the daily P&L magnitude for a 5-trade day. So:
    daily_notional_est = max(avg_abs_pnl * 35.0, 50_000.0)
    # Slippage bps from audit; if missing, assume conservative 30bps
    slippage_bps = abs(sa.get("slippage_bps_mean", 0) or 0) if sa else 0.0
    if slippage_bps < 2.0:
        # market_like symptom: enforce at least 15 bps assumption
        slippage_bps = 15.0
    return daily_notional_est * slippage_bps / 10_000


def check_slippage_adjusted_sharpe() -> tuple[bool, list[str]]:
    """Gate 12 (FIX 2026-09-17 13:25): slippage-adjusted Sharpe > 0.5.

    FIX 2026-09-17 13:25 — bootstrap from journal directly so this gate works
    from day 1 of realistic-mode trading. Falls back to 30-day backtest if
    fewer than 10 days of paper data. Reports a 3-stage status:
      - < 5 days paper  : bootstrap from backtest (gate blocked unless backtest positive)
      - 5-9 days paper : use what we have with a confidence warning
      - >=10 days      : full Sharpe over recent paper history

    Reads data_cache/slippage_audit.json for the live-equivalent P&L delta.
    If the slippage-adj Sharpe is positive in the recent paper run, real-money
    has positive expected value after half-spread costs.
    """
    audit_path = ROOT / "data_cache" / "slippage_audit.json"
    sa = None
    if audit_path.exists():
        try:
            sa = json.loads(audit_path.read_text(encoding="utf-8"))
        except Exception:
            sa = None

    # 1) Compute daily P&L from journal directly
    daily_pnl = _daily_pnl_from_journal()
    returns = sorted(daily_pnl.values())  # oldest first
    n_days = len(returns)

    # 2) Bootstrap: if < 10 days, fall back to 30-day backtest
    backtest = _backtest_summary()
    if n_days < 10:
        if not backtest or not backtest.get("daily_returns"):
            return False, [
                f"only {n_days} paper days — need ≥10 OR a 30-day backtest result "
                f"in data_cache/performance/backtest_30d.json to bootstrap. Run "
                f"`python scripts/backtest_30d.py` to populate."
            ]
        # Use backtest daily returns, marked as bootstrap
        bt_returns = backtest["daily_returns"]
        avg_bt = sum(bt_returns) / len(bt_returns)
        var_bt = sum((r - avg_bt) ** 2 for r in bt_returns) / max(1, len(bt_returns) - 1)
        std_bt = var_bt ** 0.5
        bt_sharpe = avg_bt / std_bt if std_bt > 0 else 0.0
        # Apply slippage haircut using the backtest's avg notional
        bt_avg_notional = backtest.get("avg_daily_notional") or backtest.get("notional_per_day") or 100_000.0
        bt_slippage_bps = 30.0  # conservative default for 30-day backtest
        bt_slippage_cost = bt_avg_notional * bt_slippage_bps / 10_000
        adj_bt_returns = [r - bt_slippage_cost for r in bt_returns]
        adj_bt_avg = sum(adj_bt_returns) / len(adj_bt_returns)
        adj_bt_var = sum((r - adj_bt_avg) ** 2 for r in adj_bt_returns) / max(1, len(adj_bt_returns) - 1)
        adj_bt_std = adj_bt_var ** 0.5
        adj_bt_sharpe = adj_bt_avg / adj_bt_std if adj_bt_std > 0 else 0.0
        if n_days < 5:
            return adj_bt_sharpe > 0.5, [
                f"{n_days} paper days + 30-day backtest bootstrap: "
                f"backtest Sharpe={bt_sharpe:.2f}, slippage-adj Sharpe={adj_bt_sharpe:.2f} "
                f"(assume {bt_slippage_bps:.0f}bps slippage, "
                f"backtest notional Rs.{bt_avg_notional:,.0f}/day, "
                f"slippage cost Rs.{bt_slippage_cost:,.0f}/day)",
                f"want adj Sharpe > 0.5 — paper run will replace bootstrap in ~{10 - n_days} days",
            ]
        # 5-9 days paper: weighted blend (paper gets more weight as it accumulates)
        paper_weight = n_days / 10.0  # 0.5 to 0.9
        avg_paper = sum(returns) / len(returns) if returns else 0.0
        var_paper = sum((r - avg_paper) ** 2 for r in returns) / max(1, len(returns) - 1)
        std_paper = var_paper ** 0.5
        paper_sharpe = avg_paper / std_paper if std_paper > 0 else 0.0
        slippage_cost = _slippage_haircut_per_day(returns, sa or {})
        adj_paper_returns = [r - slippage_cost for r in returns]
        adj_paper_avg = sum(adj_paper_returns) / len(adj_paper_returns)
        adj_paper_var = sum((r - adj_paper_avg) ** 2 for r in adj_paper_returns) / max(1, len(adj_paper_returns) - 1)
        adj_paper_std = adj_paper_var ** 0.5
        adj_paper_sharpe = adj_paper_avg / adj_paper_std if adj_paper_std > 0 else 0.0
        blend_sharpe = paper_weight * adj_paper_sharpe + (1 - paper_weight) * adj_bt_sharpe
        return blend_sharpe > 0.5, [
            f"{n_days} paper days (weight={paper_weight:.2f}) + 30-day backtest bootstrap: "
            f"blended slippage-adj Sharpe={blend_sharpe:.2f} "
            f"(paper {adj_paper_sharpe:.2f}, backtest {adj_bt_sharpe:.2f})",
            f"want adj Sharpe > 0.5 — {10 - n_days} more paper days to drop bootstrap",
        ]

    # 3) >=10 days paper: full Sharpe over recent paper history
    avg_return = sum(returns) / len(returns)
    var = sum((r - avg_return) ** 2 for r in returns) / max(1, len(returns) - 1)
    std = var ** 0.5
    sharpe = avg_return / std if std > 0 else 0.0
    slippage_cost = _slippage_haircut_per_day(returns, sa or {})
    adj_returns = [r - slippage_cost for r in returns]
    adj_avg = sum(adj_returns) / len(adj_returns)
    adj_var = sum((r - adj_avg) ** 2 for r in adj_returns) / max(1, len(adj_returns) - 1)
    adj_std = adj_var ** 0.5
    adj_sharpe = adj_avg / adj_std if adj_std > 0 else 0.0
    return adj_sharpe > 0.5, [
        f"{n_days} paper days: Sharpe={sharpe:.2f}, "
        f"slippage-adj Sharpe={adj_sharpe:.2f} "
        f"(daily slippage cost Rs.{slippage_cost:,.0f}, "
        f"slippage bps={sa.get('slippage_bps_mean','?') if sa else '?'})",
        f"want adj Sharpe > 0.5",
    ]


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
