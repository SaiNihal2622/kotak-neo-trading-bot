"""Daily summary — Telegram at 15:30 IST with missed-profit + live-go status.

PHASE 6 FIX 2026-09-30: replaces the missing daily Telegram summary.
Combines:
- Today's actual P&L from paper_state
- Today's missed-profit from counterfactual
- Real-life-go readiness progress
- Tomorrow's setup (regime + key events)

Runs as a single Telegram message. Designed to be invoked via:
- Force-action from the bot (no UAC)
- Or directly: python scripts/daily_summary.py [--send-tg]

Exit codes:
    0 = success
    1 = telegram send failed (no critical)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IST = timezone(timedelta(hours=5, minutes=30))

STATE_DB = PROJECT_ROOT / "data_cache" / "state.db"
PAPER_STATE = PROJECT_ROOT / "data_cache" / "paper_state.json"
LIVE_GO_STATUS = PROJECT_ROOT / "data_cache" / "live_go_status.json"
CF_LOG = PROJECT_ROOT / "data_cache" / "counterfactual_log.jsonl"


def _now_ist() -> datetime:
    return datetime.now(IST)


def _read_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _send_telegram(text: str, cred_path: Path) -> bool:
    if not cred_path.exists():
        return False
    try:
        env = {}
        for line in cred_path.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
        token = env.get("TELEGRAM_BOT_TOKEN", "")
        chat = env.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat:
            return False
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urlencode({"chat_id": chat, "text": text[:3500]}).encode("utf-8")
        req = Request(url, data=data, method="POST")
        with urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception as e:
        print(f"telegram send failed: {e}", file=sys.stderr)
        return False


def gather_today() -> dict:
    """Aggregate today's stats from paper_state + counterfactual + live_go."""
    today = _now_ist().strftime("%Y-%m-%d")

    # 1. Paper state
    ps = _read_json(PAPER_STATE, default={}) or {}
    realized = float(ps.get("realized_pnl", 0))
    cash = float(ps.get("cash", 100000))
    starting = float(ps.get("starting_capital", 100000))
    positions = ps.get("positions", {})
    pos_count = sum(1 for p in (positions.values() if isinstance(positions, dict) else []) if float(p.get("qty", 0)) != 0)

    # 2. Counterfactual
    actual_pnl_cf = 0.0
    missed_pnl = 0.0
    trades_actual = 0
    trades_skipped = 0
    bad_opens = 0
    bad_opens_pnl = 0.0
    good_opens = 0
    good_opens_pnl = 0.0
    if CF_LOG.exists():
        for line in CF_LOG.read_text(encoding="utf-8").splitlines():
            if not line.strip() or not line.startswith('{"'):
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not rec.get("ts", "").startswith(today):
                continue
            d = rec.get("decision")
            if d == "OPEN":
                trades_actual += 1
                p = float(rec.get("actual_outcome", {}).get("pnl_per_lot", 0))
                actual_pnl_cf += p
                if p < 0:
                    bad_opens += 1
                    bad_opens_pnl += p
                elif p > 0:
                    good_opens += 1
                    good_opens_pnl += p
            elif d == "HOLD":
                cf = rec.get("counterfactual", {})
                if cf.get("would_have_action") and cf.get("would_have_action") != "HOLD":
                    trades_skipped += 1
                    missed_pnl += float(rec.get("missed_pnl_per_lot", 0))

    # 3. Live-go readiness
    lg = _read_json(LIVE_GO_STATUS, default={}) or {}
    ready = lg.get("ready_for_live", False)
    cur = lg.get("current", {})
    crit = lg.get("conditions", {})

    # 4. Build summary
    sign = lambda x: "+" if x >= 0 else ""
    summary = {
        "date": today,
        "ts": _now_ist().isoformat(),
        "paper": {
            "realized_pnl": realized,
            "cash": cash,
            "starting_capital": starting,
            "open_positions": pos_count,
            "return_pct": round(100 * realized / max(1, starting), 2),
        },
        "counterfactual": {
            "trades_actual": trades_actual,
            "trades_skipped": trades_skipped,
            "actual_pnl": round(actual_pnl_cf, 2),
            "missed_pnl": round(missed_pnl, 2),
            "bad_opens": bad_opens,
            "bad_opens_pnl": round(bad_opens_pnl, 2),
            "good_opens": good_opens,
            "good_opens_pnl": round(good_opens_pnl, 2),
        },
        "live_go": {
            "ready": ready,
            "current": cur,
            "criteria": crit,
            "missing": lg.get("missing_to_ready", []),
        },
    }
    return summary


def format_telegram(summary: dict) -> str:
    """Build Telegram-friendly summary message."""
    sign = lambda x: "+" if x >= 0 else ""
    p = summary["paper"]
    cf = summary["counterfactual"]
    lg = summary["live_go"]

    lines = [
        f"📊 Daily Summary — {summary['date']}",
        "",
        f"💰 Paper P&L: Rs.{sign(p['realized_pnl'])}{p['realized_pnl']:,.0f} ({sign(p['return_pct'])}{p['return_pct']}%)",
        f"  Cash: Rs.{p['cash']:,.0f} / Starting: Rs.{p['starting_capital']:,.0f}",
        f"  Open positions: {p['open_positions']}",
    ]
    if cf["trades_actual"] > 0:
        win_rate = (cf["good_opens"] / max(1, cf["good_opens"] + cf["bad_opens"])) * 100
        lines.append("")
        lines.append(f"🎯 Today's trades: {cf['trades_actual']} ({win_rate:.0f}% win)")
        lines.append(f"  Good opens: {cf['good_opens']} (Rs.{sign(cf['good_opens_pnl'])}{cf['good_opens_pnl']:,.0f})")
        lines.append(f"  Bad opens: {cf['bad_opens']} (Rs.{sign(cf['bad_opens_pnl'])}{cf['bad_opens_pnl']:,.0f})")
    if cf["missed_pnl"] > 100:
        lines.append("")
        lines.append(f"⚠️ Missed: Rs.{sign(cf['missed_pnl'])}{cf['missed_pnl']:,.0f} on {cf['trades_skipped']} skipped signals")

    if lg["ready"]:
        lines.append("")
        lines.append("🎯 **READY FOR LIVE** — all 5 criteria met!")
    elif lg.get("missing"):
        lines.append("")
        lines.append(f"📋 Live-go missing: {', '.join(lg['missing'])}")

    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--send-tg", action="store_true", help="send Telegram")
    args = p.parse_args()

    summary = gather_today()
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))

    if args.send_tg:
        text = format_telegram(summary)
        ok = _send_telegram(text, PROJECT_ROOT / "config" / "credentials.env")
        if ok:
            print(f"\n[telegram] daily summary sent for {summary['date']}")
        else:
            print(f"\n[telegram] send failed (credentials missing or network issue)")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())