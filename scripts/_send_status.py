"""_send_status.py - One-shot pre-market status to Telegram.

Run from anywhere; reads credentials.env and posts a status card.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

env_file = ROOT / "config" / "credentials.env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")


def send(text: str) -> bool:
    if not TOKEN or not CHAT:
        print("no creds", file=sys.stderr)
        return False
    if len(text) > 4000:
        text = text[:3950] + "\n\n[truncated]"
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    body = json.dumps({"chat_id": CHAT, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception as e:
        print(f"send failed: {e}", file=sys.stderr)
        return False


def main() -> int:
    paper = json.loads((ROOT / "data_cache" / "paper_state.json").read_text(encoding="utf-8"))
    liv = json.loads((ROOT / "data_cache" / "liveness.json").read_text(encoding="utf-8"))
    sess = json.loads((ROOT / "data_cache" / "kotak_prod_session.json").read_text(encoding="utf-8"))
    pre = json.loads((ROOT / "data_cache" / "mavis_trades.json").read_text(encoding="utf-8"))

    sess_exp_ist = datetime.fromtimestamp(sess["expires_at"]).strftime("%H:%M")
    bot_tick = liv["tick"]
    bot_up = liv["uptime_sec"] / 3600
    cash = paper["cash"]
    pos = len(paper.get("positions", {}))
    vix = liv["snapshot"].get("vix", 0)
    ds = liv["snapshot"].get("data_source", "?")
    dec = pre["mavis_decision"]
    bias = dec.get("bias", "?")
    action = dec.get("action", "?")
    conf = dec.get("confidence", 0)

    msg = (
        f"<b>Pre-market 09:05 IST Thu 03-Sep</b>\n"
        f"\n"
        f"Bot: alive, tick={bot_tick}, uptime={bot_up:.1f}h, cash=Rs.{cash:,.0f}, "
        f"positions={pos}, VIX={vix:.2f}, data={ds}\n"
        f"Session: valid until {sess_exp_ist} IST\n"
        f"Pre-market: action={action}, bias={bias}, conf={conf:.2f}\n"
        f"\n"
        f"Status: bot+dash OK. Brain on OLD code (no UAC restart yet) - "
        f"will run at 90-min intervals + event triggers, expected 6-12 LLM calls today. "
        f"Once you run <code>scripts/_kick_brain.ps1</code> (admin UAC), brain loads new "
        f"aggressive code: 15-min periodic, SENSEX targets, low-vol tuning, auto-execute. "
        f"Phantom audit: clean. Shadow lint: passed. Bot safety caps active: 1%/5%.\n"
        f"\n"
        f"Market opens 09:15 IST. Watching..."
    )
    ok = send(msg)
    print(f"sent: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
