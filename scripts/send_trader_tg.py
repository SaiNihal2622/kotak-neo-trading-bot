"""send_trader_tg.py — Format and send trader desk decision to Telegram.

Usage:
  python scripts/send_trader_tg.py                # reads brain_state.json
  python scripts/send_trader_tg.py --summary       # short summary only
  python scripts/send_trader_tg.py --always        # send even if not changed
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    _env = ROOT / "config" / "credentials.env"
    if _env.exists():
        load_dotenv(str(_env))
except Exception:
    pass

BRAIN_STATE = ROOT / "data_cache" / "brain_state.json"
BRAIN_ACTIONS = ROOT / "data_cache" / "brain_actions.json"
PAPER_STATE = ROOT / "data_cache" / "paper_state.json"
SENT_LOG = ROOT / "data_cache" / "trader_tg_sent.json"


def get_creds() -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        env_file = ROOT / "config" / "credentials.env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    return token, chat_id


def send_telegram(text: str) -> bool:
    token, chat_id = get_creds()
    if not token or not chat_id:
        print("send_trader_tg: no TELEGRAM creds", file=sys.stderr)
        return False
    # Telegram has 4096 char limit per message
    if len(text) > 4000:
        text = text[:3950] + "\n\n[truncated]"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as e:
        print(f"send_trader_tg: send failed: {e}", file=sys.stderr)
        return False


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def format_message(args) -> str | None:
    brain = load_json(BRAIN_STATE)
    actions_payload = load_json(BRAIN_ACTIONS)
    paper = load_json(PAPER_STATE)
    last = brain.get("last_decision")
    if not last:
        return None
    last_ts = last.get("timestamp", "")
    bias = last.get("bias", "?")
    conf = last.get("confidence", 0)
    risk = last.get("risk_budget_pct", 0)
    rationale = last.get("rationale", "")
    source = last.get("source", "?")
    cash = paper.get("cash", 0)
    realized = paper.get("realized_pnl", 0)
    market = actions_payload.get("note", "regular")
    ist = last.get("ist_time", "")

    # Action count and types
    action_list = actions_payload.get("actions", []) or []
    n_actions = len(action_list)
    types = [a.get("type", "?") for a in action_list]

    # EMOJI
    bias_emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪", "cautious": "🟡"}.get(bias, "❔")
    src_emoji = "🤖" if source == "minimax" else "⚠️"

    if args.summary:
        msg = (
            f"{bias_emoji} <b>{bias.upper()}</b> | conf {conf:.2f} | risk {risk:.0f}% | "
            f"actions {n_actions} ({', '.join(types) if types else 'none'})\n"
            f"{src_emoji} {source} | {ist} IST | market: {market}\n"
            f"💰 Rs.{cash:,.0f} | 📈 P&L Rs.{realized:+,.0f}"
        )
        return msg

    msg_lines = [
        f"{bias_emoji} <b>TRADER DESK</b> — {bias.upper()} (conf {conf:.2f}, risk {risk:.0f}%)",
        f"⏰ {ist} IST | market={market} | {src_emoji} {source}",
        f"💰 Cash Rs.{cash:,.0f} | 📈 P&L Rs.{realized:+,.0f}",
        f"📝 {rationale[:280]}",
    ]
    if action_list:
        msg_lines.append(f"🎯 {n_actions} action(s):")
        for a in action_list[:5]:
            atype = a.get("type", "?")
            astrat = a.get("strategy", "?")
            aund = a.get("underlying", "?")
            arat = (a.get("rationale") or "")[:120]
            msg_lines.append(f"  - <b>{atype}</b> {astrat} {aund} | {arat}")
    return "\n".join(msg_lines)


def should_send(force: bool) -> bool:
    if force:
        return True
    # Send if last decision changed since last sent
    if not SENT_LOG.exists():
        return True
    sent = load_json(SENT_LOG)
    brain = load_json(BRAIN_STATE)
    last_ts = brain.get("last_decision", {}).get("timestamp", "")
    if sent.get("last_ts") != last_ts:
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true", help="Short summary only")
    parser.add_argument("--always", action="store_true", help="Send even if unchanged")
    args = parser.parse_args()

    if not should_send(args.always):
        return 0

    msg = format_message(args)
    if not msg:
        print("send_trader_tg: no decision yet", file=sys.stderr)
        return 1
    ok = send_telegram(msg)
    if ok:
        brain = load_json(BRAIN_STATE)
        SENT_LOG.write_text(json.dumps({
            "last_ts": brain.get("last_decision", {}).get("timestamp", ""),
            "sent_at": datetime.utcnow().isoformat() + "Z",
        }, indent=2), encoding="utf-8")
        print("send_trader_tg: sent OK")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
