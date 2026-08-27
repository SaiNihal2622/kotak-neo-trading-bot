"""One-shot 5-line pre-market brief to Telegram. Run by cron after thesis_engine premarket."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

# Force UTF-8 stdout so emojis print on Windows cp1252 console
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

# Load creds from .env
for line in (ROOT / "config" / "credentials.env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip())

THESIS = ROOT / "data_cache" / "thesis" / "latest.json"
t = json.loads(THESIS.read_text(encoding="utf-8"))

ist = t.get("ist_time", "")
regime = (t.get("regime") or "?").upper()
bias = (t.get("bias") or "?").upper()
conf = float(t.get("confidence", 0))
risk = t.get("risk_budget_pct", 0)
maxpos = t.get("max_positions", 0)
em = t.get("expected_move_pts")
rng = t.get("expected_range") or [None, None]
strats = t.get("preferred_strategies") or []
xmkt = (t.get("data") or {}).get("xmkt") or {}
vix = xmkt.get("india_vix")
crude = xmkt.get("crude_oil")
spot = xmkt.get("nifty_spot")
oi = (t.get("data") or {}).get("oi") or {}

lines = [
    f"📊 *PRE-MARKET BRIEF* — {ist} IST",
    f"↔️ Regime: *{regime}* | Bias: *{bias}* | Conf: *{conf:.0%}*",
    f"🎯 NIFTY spot {spot:.0f} | VIX {vix:.1f} | Exp move ±{em:.0f} pts ({rng[0]:.0f}–{rng[1]:.0f})"
    if spot and vix and em else f"🎯 NIFTY spot {spot:.0f} | Exp move ±{em:.0f} pts ({rng[0]:.0f}–{rng[1]:.0f})",
    f"💰 Risk: {risk:.0f}% / max {maxpos} pos | Play: {', '.join(strats[:2]) if strats else '—'}",
]

# 5th line: OI + global cues (or fallback caveat)
oi_state = "OI pending (live at 09:00)" if not oi.get("available") else "OI live"
cues = []
if crude: cues.append(f"Crude ${crude:.0f}")
if xmkt.get("global_cues"): cues.append(xmkt["global_cues"])
fifth = f"⚠️ {oi_state} | " + " | ".join(cues) if cues else f"⚠️ {oi_state} | No fresh catalysts"
lines.append(fifth)

msg = "\n".join(lines)
print(msg)
print("---")

token = os.environ.get("TELEGRAM_BOT_TOKEN")
chat = os.environ.get("TELEGRAM_CHAT_ID")
if not (token and chat):
    print("NO_TG_CREDS")
    sys.exit(1)

import httpx
r = httpx.post(
    f"https://api.telegram.org/bot{token}/sendMessage",
    json={"chat_id": chat, "text": msg, "parse_mode": "Markdown", "disable_web_page_preview": True},
    timeout=10,
)
print(f"tg status={r.status_code} resp={r.text[:200]}")
sys.exit(0 if r.status_code == 200 else 2)
