"""send_thesis_flip.py — Send a THESIS FLIP alert to Telegram when bias/confidence shift."""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
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
        print("send_thesis_flip: no TELEGRAM creds", file=sys.stderr)
        return False
    if len(text) > 4000:
        text = text[:3950] + "\n\n[truncated]"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as e:
        print(f"send_thesis_flip: send failed: {e}", file=sys.stderr)
        return False


def load_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    thesis_dir = ROOT / "data_cache" / "thesis"
    latest = load_json(thesis_dir / "latest.json")

    # Find previous archived thesis. thesis_engine.py just wrote a new file
    # in this same run with the same ts as latest.json, so take the second-newest.
    all_archives = sorted(thesis_dir.glob("thesis_*.json"), key=lambda p: p.stat().st_mtime)
    if len(all_archives) < 2:
        print("send_thesis_flip: no prior thesis to compare", file=sys.stderr)
        return 1
    prev_path = all_archives[-2]
    prev = load_json(prev_path)

    new_bias = latest.get("bias", "?")
    new_conf = float(latest.get("confidence", 0))
    new_regime = latest.get("regime", "?")
    new_risk = latest.get("risk_budget_pct", 0)
    new_strats = latest.get("preferred_strategies", [])

    prev_bias = prev.get("bias", "?")
    prev_conf = float(prev.get("confidence", 0))
    prev_regime = prev.get("regime", "?")
    prev_risk = prev.get("risk_budget_pct", 0)
    prev_strats = prev.get("preferred_strategies", [])

    bias_flipped = new_bias != prev_bias
    conf_drop = prev_conf - new_conf
    conf_dropped = conf_drop > 0.15

    if not (bias_flipped or conf_dropped):
        print(f"send_thesis_flip: no flip (bias {prev_bias}->{new_bias}, conf {prev_conf}->{new_conf})")
        return 0

    ist = latest.get("ist_time", "")
    narrative = latest.get("narrative", "")

    def emoji(b):
        return {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪", "cautious": "🟡"}.get(b, "❔")

    lines = [
        "🔔 <b>THESIS FLIP</b>",
        f"⏰ {ist} IST",
        f"regime: {prev_regime} → <b>{new_regime}</b>",
        f"bias: {emoji(prev_bias)} {prev_bias} (conf {prev_conf:.2f}) → {emoji(new_bias)} <b>{new_bias}</b> (conf {new_conf:.2f})",
        f"risk_budget: {prev_risk}% → {new_risk}%",
    ]
    if bias_flipped:
        lines.append(f"⚠️ <b>BIAS FLIPPED:</b> {prev_bias} → {new_bias}")
    if conf_dropped:
        lines.append(f"📉 <b>CONFIDENCE DROP:</b> -{conf_drop:.2f} (>0.15 threshold)")
    added = [s for s in new_strats if s not in prev_strats]
    removed = [s for s in prev_strats if s not in new_strats]
    if added or removed:
        lines.append(f"strategies: +{added or '∅'} / -{removed or '∅'}")
    lines.append("")
    lines.append(f"📝 {narrative}")

    msg = "\n".join(lines)
    ok = send_telegram(msg)
    print(f"send_thesis_flip: sent OK={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
