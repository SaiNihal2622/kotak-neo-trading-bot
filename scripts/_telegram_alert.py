"""_telegram_alert.py - send Telegram alerts for key system events.

FIX 2026-09-04 12:30: confluence detector finds 3+ signals but no alert fires.
This script provides a function to send Telegram messages. Used by:
  - _confluence_check.py (when confluence is detected)
  - bot (when UnboundLocalError happens)
  - _force_square_now.py (when positions are force-closed)

Telegram credentials are read from config/credentials.env.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()


def get_creds():
    """Read Telegram credentials from config/credentials.env."""
    env_file = ROOT / "config" / "credentials.env"
    if not env_file.exists():
        return None, None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    return os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")


def _settings_telegram_enabled() -> bool:
    """FIX 2026-09-21 03:25: respect settings.yaml alerts.telegram.enabled.

    Returns True only if Telegram is explicitly enabled in the YAML. Default
    is False (user wants dashboard, not Telegram). Avoids 401/timeout retries
    that pollute logs and waste cycles.
    """
    try:
        cfg_path = ROOT / "config" / "settings.yaml"
        if not cfg_path.exists():
            return False
        in_alerts = False
        in_telegram = False
        for raw in cfg_path.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            if not in_alerts:
                if stripped == "alerts:":
                    in_alerts = True
                continue
            if in_alerts and not in_telegram:
                if stripped.startswith("telegram:"):
                    in_telegram = True
                elif stripped and not raw.startswith(" ") and not raw.startswith("\t"):
                    return False
                continue
            if in_telegram:
                if stripped.startswith("enabled:"):
                    val = stripped.split(":", 1)[1].strip().lower()
                    return val in ("true", "yes", "on", "1")
                if stripped and not raw.startswith(" ") and not raw.startswith("\t"):
                    return False
        return False
    except Exception:
        return False


def send_telegram(text: str, max_len: int = 4000) -> bool:
    """Send a Telegram message. Truncates if too long.

    FIX 2026-09-21 03:25: gate on settings.yaml alerts.telegram.enabled. If
    the user has disabled Telegram, log a one-line note and return False
    instead of attempting to send.
    """
    if not _settings_telegram_enabled():
        print("telegram disabled in settings.yaml (alerts.telegram.enabled=false)", file=sys.stderr)
        return False
    token, chat_id = get_creds()
    if not token or not chat_id:
        print("no Telegram creds", file=sys.stderr)
        return False
    if len(text) > max_len:
        text = text[:max_len - 50] + "\n\n[truncated]"
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
        print(f"send failed: {e}", file=sys.stderr)
        return False


def main():
    if len(sys.argv) < 2:
        print("usage: python _telegram_alert.py <text>")
        sys.exit(1)
    text = sys.argv[1]
    ok = send_telegram(text)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
