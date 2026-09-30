"""Daily missed-profit summary — runs at 15:30 IST after market close.

PHASE 6 FIX 2026-09-30: aggregates today's counterfactual records into
a Telegram alert. Shows:
- Today's actual P&L
- Today's missed P&L (what we could have made)
- Top missed opportunities
- Lessons learned (used by brain prompt tomorrow)

Called by:
1. The in-process scheduler in scripts/quant_service.py (15:30 IST slot)
2. Manually:  python scripts/daily_missed_profit.py [--send-tg]

Outputs JSON to stdout for piping into Telegram.

Exit codes:
    0 = summary computed (or sent)
    1 = error
    2 = no data (counterfactual_log.jsonl missing)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IST = timezone(timedelta(hours=5, minutes=30))


def _now_ist() -> datetime:
    return datetime.now(IST)


def compute_summary(target_date: str) -> dict:
    """Delegate to counterfactual.compute_daily_summary."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from system.brain.counterfactual import compute_daily_summary
    return compute_daily_summary(target_date)


def format_telegram(summary: dict) -> str:
    """Build a Telegram-friendly summary message."""
    if not summary:
        return "[missed-profit] no summary available"
    date = summary.get("date", "today")
    actual = summary.get("actual_pnl", 0)
    missed = summary.get("missed_pnl", 0)
    skipped = summary.get("trades_skipped", 0)
    taken = summary.get("trades_actual", 0)
    lessons = summary.get("lessons", [])

    sign = lambda x: "+" if x >= 0 else ""
    lines = [
        f"[missed-profit {date}]",
        f"  actual P&L:  Rs.{sign(actual)}{actual:,.0f} ({taken} trades)",
        f"  missed P&L:  Rs.{sign(missed)}{missed:,.0f} ({skipped} skipped signals)",
    ]
    if summary.get("missed_pct"):
        lines.append(f"  missed ratio: {summary['missed_pct']}%")
    if lessons:
        lines.append("")
        lines.append("Lessons:")
        for lesson in lessons[:3]:
            lines.append(f"  • {lesson}")
    return "\n".join(lines)


def send_telegram(text: str, credentials_path: Path) -> bool:
    """Send Telegram via credentials.env (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)."""
    if not credentials_path.exists():
        return False
    try:
        env_lines = credentials_path.read_text(encoding="utf-8-sig").splitlines()
        env = {}
        for line in env_lines:
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
        token = env.get("TELEGRAM_BOT_TOKEN", "")
        chat = env.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat:
            return False
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urlencode({"chat_id": chat, "text": text[:3500], "parse_mode": "HTML"}).encode("utf-8")
        req = Request(url, data=data, method="POST")
        with urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception as e:
        print(f"telegram send failed: {e}", file=sys.stderr)
        return False


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--date", help="YYYY-MM-DD (default: today IST)")
    p.add_argument("--send-tg", action="store_true",
                   help="send the summary to Telegram via credentials.env")
    args = p.parse_args()

    target = args.date or _now_ist().strftime("%Y-%m-%d")
    summary = compute_summary(target)

    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if args.send_tg:
        text = format_telegram(summary)
        creds = PROJECT_ROOT / "config" / "credentials.env"
        ok = send_telegram(text, creds)
        if not ok:
            print("telegram send skipped (no credentials or failed)", file=sys.stderr)
            return 1
        print(f"[missed-profit] telegram sent for {target}")

    return 0


if __name__ == "__main__":
    sys.exit(main())