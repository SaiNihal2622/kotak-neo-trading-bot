"""Send the paper_state.json + trades_state.json to the user's Telegram
as a 'saved message' backup. Run at 15:45 IST (after EOD square-off + report).
This is the user's offline backup if the local files get corrupted.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / "config" / "credentials.env")

import httpx

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def main() -> int:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("telegram creds missing")
        return 1

    sp = ROOT / "data_cache" / "paper_state.json"
    tp = ROOT / "data_cache" / "trades_state.json"
    today = datetime.utcnow().strftime("%Y-%m-%d")

    summary = []
    if sp.exists():
        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
            n_orders = len(data.get("orders", {}))
            n_pos = len(data.get("positions", {}))
            cash = data.get("cash", 0)
            realized = data.get("realized_pnl", 0)
            summary.append(
                f"paper_state: cash=Rs.{cash:,.0f} realized=Rs.{realized:,.0f} "
                f"orders={n_orders} positions={n_pos}"
            )
        except Exception as e:
            summary.append(f"paper_state: read error {e}")
    if tp.exists():
        try:
            data = json.loads(tp.read_text(encoding="utf-8"))
            n = len(data.get("trades", {}))
            n_open = sum(1 for t in data.get("trades", {}).values() if t.get("closed_at") is None)
            summary.append(f"trades_state: {n} trades ({n_open} open)")
        except Exception as e:
            summary.append(f"trades_state: read error {e}")

    msg = f"**EOD backup — {today}**\n" + "\n".join(summary)
    print(msg.encode("ascii", "replace").decode("ascii"))

    r = httpx.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
        timeout=10,
    )
    print(f"summary sent: {r.json().get('ok')}")

    # also send the paper_state as a document (json)
    if sp.exists():
        with sp.open("rb") as f:
            r2 = httpx.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument",
                data={"chat_id": TELEGRAM_CHAT_ID,
                      "caption": f"paper_state.json — {today}"},
                files={"document": (f"paper_state_{today}.json", f, "application/json")},
                timeout=30,
            )
        print(f"paper_state file sent: {r2.json().get('ok')}")

    if tp.exists():
        with tp.open("rb") as f:
            r3 = httpx.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument",
                data={"chat_id": TELEGRAM_CHAT_ID,
                      "caption": f"trades_state.json — {today}"},
                files={"document": (f"trades_state_{today}.json", f, "application/json")},
                timeout=30,
            )
        print(f"trades_state file sent: {r3.json().get('ok')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
