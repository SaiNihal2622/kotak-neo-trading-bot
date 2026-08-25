"""Pre-market thesis brief — formatted for Telegram, written from latest thesis.

Run by cron at 08:25 Mon-Fri after thesis_engine has run.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Force UTF-8 stdout so emojis print cleanly on Windows cp1252 consoles
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

from loguru import logger
from kotak_bot.utils.clock import now_ist

THESIS_LATEST = ROOT / "data_cache" / "thesis" / "latest.json"


def build_brief() -> str | None:
    if not THESIS_LATEST.exists():
        return None
    try:
        t = json.loads(THESIS_LATEST.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"brief: failed to read thesis: {e}")
        return None

    bias_emoji = {
        "bullish": "🟢", "bearish": "🔴", "neutral": "⚪", "cautious": "🟡"
    }.get(t.get("bias", "neutral"), "⚪")

    regime_emoji = {
        "pin": "📌", "range": "↔️", "breakout_prone": "💥",
        "volatile": "⚡", "breakout_up": "📈", "breakout_down": "📉", "quiet": "😴"
    }.get(t.get("regime", "unknown"), "❓")

    lines = [
        f"📊 *PRE-MARKET THESIS BRIEF* — {t.get('ist_time','')}",
        f"",
        f"{regime_emoji} Regime: *{t.get('regime','?').upper()}*  "
        f"{bias_emoji} Bias: *{t.get('bias','?').upper()}*  "
        f"(conf {float(t.get('confidence', 0)):.0%})",
        f"💰 Risk budget: {t.get('risk_budget_pct', 0):.0f}% capital, "
        f"max {t.get('max_positions', 0)} positions",
    ]

    rng = t.get("expected_range") or [None, None]
    em = t.get("expected_move_pts")
    if em and rng[0] and rng[1]:
        lines.append(f"📏 Expected move: ±{em:.0f} pts (range {rng[0]:.0f}–{rng[1]:.0f})")

    oi = (t.get("data") or {}).get("oi") or {}
    if oi.get("available"):
        parts = []
        if oi.get("support"): parts.append(f"sup {oi['support']}")
        if oi.get("resistance"): parts.append(f"res {oi['resistance']}")
        if oi.get("max_pain"): parts.append(f"maxpain {oi['max_pain']}")
        if oi.get("pcr") is not None: parts.append(f"PCR {oi['pcr']:.2f}")
        if parts:
            lines.append(f"🎯 OI: " + " | ".join(parts))
    else:
        lines.append("🎯 OI: (no live chain yet — refresh at 09:00)")

    macro = (t.get("data") or {}).get("macro") or {}
    if macro.get("next_event"):
        evt = macro["next_event"]
        name = evt.get("name") if isinstance(evt, dict) else evt
        wmin = macro.get("window_min")
        if wmin is not None:
            lines.append(f"📅 Event: {name} in {int(wmin)} min")

    xmkt = (t.get("data") or {}).get("xmkt") or {}
    cues = []
    if xmkt.get("india_vix"): cues.append(f"VIX {xmkt['india_vix']:.1f}")
    if xmkt.get("crude_oil"): cues.append(f"Crude ${xmkt['crude_oil']:.0f}")
    if xmkt.get("usdinr"): cues.append(f"USD/INR {xmkt['usdinr']:.2f}")
    if xmkt.get("dow_fut"): cues.append(f"Dow fut {xmkt['dow_fut']:.0f}")
    if cues:
        lines.append(f"🌐 Global: " + " | ".join(cues))

    news = (t.get("data") or {}).get("news") or {}
    if news.get("score") is not None and news.get("n_items", 0) > 0:
        sign = "+" if news["score"] > 0 else ""
        lines.append(f"📰 News: {sign}{news['score']:.2f} (n={news['n_items']})")
        for h in (news.get("headlines") or [])[:3]:
            if h:
                lines.append(f"   • {h[:140]}")

    if t.get("specific_strikes") and isinstance(t["specific_strikes"], dict):
        ss = t["specific_strikes"]
        ce = ss.get("ce_short")
        pe = ss.get("pe_short")
        if ce and pe:
            lines.append(f"\n🎯 *Strikes (OI-aware)*: CE short {ce} | PE short {pe}")

    if t.get("preferred_strategies"):
        lines.append(f"\n✅ Play: {', '.join(t['preferred_strategies'][:3])}")
    if t.get("avoid_strategies"):
        lines.append(f"⛔ Avoid: {', '.join(t['avoid_strategies'][:3])}")

    trig = t.get("triggers") or {}
    if trig.get("force_square") or trig.get("no_new_trades"):
        flags = []
        if trig.get("force_square"): flags.append("FORCE_SQUARE")
        if trig.get("no_new_trades"): flags.append("NO_NEW_TRADES")
        lines.append(f"\n🚨 *TRIGGERS: {' '.join(flags)}*")

    lines.append(f"\n_{t.get('narrative','')}_")
    lines.append(f"\n_next refresh: 30min | detailed: data_cache/thesis/latest.json_")
    return "\n".join(lines)


def deliver_telegram(msg: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    try:
        import httpx
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": msg, "parse_mode": "Markdown", "disable_web_page_preview": True},
            timeout=10,
        )
        return True
    except Exception as e:
        logger.warning(f"brief: telegram send failed: {e}")
        return False


def main() -> int:
    msg = build_brief()
    if not msg:
        print("NO_THESIS")
        return 1
    print(msg)
    sent = deliver_telegram(msg)
    print(f"\n--- telegram: {'sent' if sent else 'skipped (no creds)'} ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
