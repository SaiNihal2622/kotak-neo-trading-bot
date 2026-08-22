"""Send the Monday pre-market brief to Telegram.

Reads: data_cache/monday_brief.json
Sends: formatted summary to @Kotak_Neo_Bot (chat_id from credentials.env)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
BRIEF_PATH = ROOT / "data_cache" / "monday_brief.json"
INTEL_PATH = ROOT / "data_cache" / "weekend_intel.json"
CRED_PATH = ROOT / "config" / "credentials.env"


def load_creds() -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if (not token or not chat_id) and CRED_PATH.exists():
        for line in CRED_PATH.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    return token, chat_id


def send_telegram(text: str) -> bool:
    token, chat_id = load_creds()
    if not token or not chat_id:
        print("send_monday_brief: no TELEGRAM creds", file=sys.stderr)
        return False
    if len(text) > 4000:
        text = text[:3950] + "\n\n[truncated]"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as e:
        print(f"send_monday_brief: send failed: {e}", file=sys.stderr)
        return False


def format_brief() -> str:
    if not BRIEF_PATH.exists():
        return "❌ monday_brief.json missing — run weekend_intel.py + monday_brief.py first"
    brief = json.loads(BRIEF_PATH.read_text(encoding="utf-8"))
    intel = json.loads(INTEL_PATH.read_text(encoding="utf-8")) if INTEL_PATH.exists() else {}
    markets = intel.get("markets", {})

    def fmt_num(v, dec=0):
        if v is None:
            return "n/a"
        return f"{v:,.{dec}f}"

    def fmt_pct(v, dec=2):
        if v is None:
            return "n/a"
        return f"{v:+.{dec}f}%"

    lines = []
    lines.append(f"🗞️ <b>MONDAY PRE-MARKET BRIEF</b>")
    lines.append(f"<i>{brief.get('next_session_open_ist', '?')}</i>")
    lines.append("")
    # Markets
    lines.append("📊 <b>Weekend markets (5d)</b>:")
    nifty = markets.get("NIFTY", {})
    if nifty:
        lines.append(f"• NIFTY: {fmt_num(nifty.get('last'))} ({fmt_pct(nifty.get('change_5d_pct'))})")
    bn = markets.get("BANKNIFTY", {})
    if bn:
        lines.append(f"• BANKNIFTY: {fmt_num(bn.get('last'))} ({fmt_pct(bn.get('change_5d_pct'))})")
    ivix = markets.get("INDIA_VIX", {})
    if ivix:
        regime_ivix = "calm" if ivix.get("last", 15) < 12 else "elevated" if ivix.get("last", 15) > 16 else "normal"
        lines.append(f"• India VIX: {fmt_num(ivix.get('last'), 1)} ({regime_ivix})")
    usdinr = markets.get("USDINR", {})
    if usdinr:
        lines.append(f"• USD/INR: {fmt_num(usdinr.get('last'), 2)} ({fmt_pct(usdinr.get('change_5d_pct'))})")
    wti = markets.get("WTI_CRUDE", {})
    if wti:
        flag = " ⚠️" if abs(wti.get("change_5d_pct", 0)) > 2 else ""
        lines.append(f"• WTI Crude: ${fmt_num(wti.get('last'), 2)} ({fmt_pct(wti.get('change_5d_pct'))}){flag}")
    gold = markets.get("GOLD", {})
    if gold:
        flag = " ⚠️" if abs(gold.get("change_5d_pct", 0)) > 3 else ""
        lines.append(f"• Gold: ${fmt_num(gold.get('last'), 0)} ({fmt_pct(gold.get('change_5d_pct'))}){flag}")
    sp = markets.get("SP500", {})
    if sp:
        lines.append(f"• S&P 500: {fmt_num(sp.get('last'))} ({fmt_pct(sp.get('change_5d_pct'))})")
    nq = markets.get("NASDAQ", {})
    if nq:
        lines.append(f"• Nasdaq: {fmt_num(nq.get('last'))} ({fmt_pct(nq.get('change_5d_pct'))})")
    us_vix = markets.get("US_VIX", {})
    if us_vix:
        regime_vix = "calm" if us_vix.get("last", 15) < 13 else "elevated" if us_vix.get("last", 15) > 18 else "normal"
        lines.append(f"• US VIX: {fmt_num(us_vix.get('last'), 1)} ({regime_vix})")
    lines.append("")
    # Regime + gap
    regime = brief.get("regime_hint", "neutral")
    gap = brief.get("india_open_gap_signal", "flat")
    regime_emoji = {"risk_on": "🟢", "risk_off": "🔴", "neutral": "🟡"}.get(regime, "⚪")
    gap_emoji = {"gap_up": "⬆️", "gap_down": "⬇️", "flat": "➡️"}.get(gap, "➡️")
    lines.append(f"{regime_emoji} <b>Regime hint</b>: {regime}")
    lines.append(f"{gap_emoji} <b>Open gap signal</b>: {gap}")
    lines.append("")
    # Risks
    risks = brief.get("key_risks", [])
    if risks:
        lines.append("🚨 <b>Key risks</b>:")
        for r in risks[:5]:
            lines.append(f"• {r}")
        lines.append("")
    # Catalysts
    catalysts = brief.get("key_catalysts", [])
    if catalysts:
        lines.append("✨ <b>Key catalysts</b>:")
        for c in catalysts[:4]:
            lines.append(f"• {c}")
        lines.append("")
    # Macro events
    events = brief.get("macro_events_next_7d", [])
    if events:
        lines.append("📅 <b>Upcoming macro (7d)</b>:")
        for e in events[:4]:
            lines.append(f"• {e['datetime_ist'][:10]}: {e['name']} (imp {e.get('importance', '?')})")
        lines.append("")
    # Posture
    posture = brief.get("recommended_posture", "normal")
    risk_pct = brief.get("max_risk_per_trade_pct", 2.0)
    skip_30 = brief.get("skip_first_30min", False)
    strategies = brief.get("preferred_strategies", [])
    rationale = brief.get("rationale", "")
    posture_emoji = {"conservative": "🛡️", "normal": "⚖️", "aggressive": "🚀"}.get(posture, "⚖️")
    lines.append(f"{posture_emoji} <b>RECOMMENDED POSTURE: {posture.upper()}</b>")
    lines.append(f"   • Max risk: {risk_pct}% per trade")
    lines.append(f"   • Skip first 30 min: {'YES' if skip_30 else 'no'}")
    if strategies:
        lines.append(f"   • Strategies: {', '.join(strategies)}")
    if rationale:
        lines.append(f"   • Rationale: {rationale}")
    lines.append("")
    # Top 3 weekend news
    news = intel.get("key_news", [])
    interesting = [n for n in news if n.get("sentiment") in ("bullish", "bearish", "event")][:3]
    if interesting:
        lines.append("📰 <b>Top weekend headlines</b>:")
        for n in interesting:
            emoji = {"bullish": "🟢", "bearish": "🔴", "event": "⚪"}.get(n.get("sentiment"), "⚪")
            lines.append(f"{emoji} {n['title'][:120]}")
        lines.append("")
    lines.append(f"<i>Source: {intel.get('as_of', '?')} · "
                 f"{intel.get('tickers_fetched', 0)} tickers · "
                 f"{intel.get('news_count', 0)} headlines</i>")
    return "\n".join(lines)


def main() -> int:
    text = format_brief()
    print(text)
    if "--no-send" in sys.argv:
        return 0
    if send_telegram(text):
        print("\n[send_monday_brief] Telegram sent ✓")
        return 0
    print("\n[send_monday_brief] Telegram send FAILED", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
