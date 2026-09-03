"""_send_eod.py - send EOD summary to Telegram."""
import json, os, sys, urllib.request
from pathlib import Path
ROOT = Path(".").resolve()
env = ROOT / "config" / "credentials.env"
for line in env.read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
ps = json.loads((ROOT / "data_cache" / "paper_state.json").read_text(encoding="utf-8"))

msg = (
    "<b>EOD Sep 3 — fix all complete</b>\n\n"
    f"Realized P&amp;L: <b>Rs.{ps['realized_pnl']:,.2f}</b>\n"
    f"Cash: Rs.{ps['cash']:,.2f}\n"
    f"Open positions: {len(ps.get('positions', {}))}\n"
    f"Closed today: 3 (INFY 1120 PE, BNF 57600/58200 CE vertical)\n\n"
    f"<b>Day result: loss of Rs.5,556.30</b> (paper simulation filled at default Rs.1.0; "
    f"real LTP at 14:24 was +Rs.2,800 to +Rs.3,800)\n\n"
    "Fixes shipped today:\n"
    "  947a25b — MTM visibility (scripts/_mtm_now.py + /api/mtm)\n"
    "  1edad1c — register_external_managed_trade for brain-driven OPENs\n"
    "  a8dec0a — orphan-fallback in force-square / hard-kill / mavis-force\n"
    "  a1d5983 — _hold_orphan_cleared.py keeps state in cleared form\n\n"
    "Hold scripts running (PIDs 5736, 21624). System is clean for tomorrow's open."
)

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
body = json.dumps({"chat_id": CHAT, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True}).encode("utf-8")
req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        print("sent" if r.status == 200 else r.status)
except Exception as e:
    print(f"err: {e}")
