"""Send a Telegram report on the UAC fix. One-shot helper, can be deleted after."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load credentials (SYSTEM context has no env vars)
for line in (ROOT / "config" / "credentials.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from scripts._telegram_alert import send_telegram

# Get live state
liveness = json.loads((ROOT / "data_cache" / "liveness.json").read_text(encoding="utf-8"))
paper = json.loads((ROOT / "data_cache" / "paper_state.json").read_text(encoding="utf-8"))

msg = (
    "UAC PROBLEM FIXED (no-UAC daily task install)\n\n"
    "Root cause: ConsentPromptBehaviorAdmin=5 - UAC prompts for credentials on "
    "non-Windows binaries (Python, .bat, .ps1). The dialog auto-canceled when no "
    "password was entered.\n\n"
    "Fix: the bot (NSSM, runs as LocalSystem) now installs the 3 daily tasks "
    "via schtasks /create /RU SYSTEM /RL HIGHEST when you write "
    '{"action": "INSTALL_TASKS"} to data_cache/mavis_force_action.json. '
    "No UAC dialog. No click. No password.\n\n"
    "VERIFIED:\n"
    "  + 3 tasks installed and confirmed by bot own schtasks /query\n"
    "  + Pre-commit hook catches the 5th shadow-import class (on sys, not Order)\n"
    "  + 3 regression tests pass\n"
    "  + daily_autonomy.py auto-loads credentials.env for SYSTEM context\n\n"
    "DAILY TASKS (will fire as SYSTEM):\n"
    "  * kotak-pre-market-self-heal @ 08:25 IST\n"
    "  * kotak-eod-pnl-evaluator  @ 15:30 IST\n"
    "  * kotak-nightly-state-backup @ 23:00 IST\n\n"
    "BUTTON-LESS INSTALLER:\n"
    "  Just double-click INSTALL.bat - it writes the action JSON for you.\n\n"
    "COMMITS THIS SESSION:\n"
    "  d8f475c feat(bot): no-UAC daily task install via SYSTEM-running bot\n"
    "  2de1eeb docs: AGENTS.md + INSTALL/UNINSTALL.bat\n\n"
    "5th SHADOW-IMPORT BUG (same class, new variable):\n"
    "  import sys inside run_paper() at line 1252 made sys local for the\n"
    "  whole function, breaking sys.exit(0) at line 1111 (RESTART_BOT branch).\n"
    "  Bot could not self-restart. Fixed by removing both in-function sys\n"
    "  imports. Linter now catches this class via usage-before-import check.\n\n"
    f"SYSTEM STATE:\n"
    f"  * Bot alive, tick={liveness.get('tick', '?')}, uptime={liveness.get('uptime_sec', 0)/60:.1f} min\n"
    f"  * Realized P&L: Rs.{paper.get('realized_pnl', 0):.2f}\n"
    f"  * Open positions: {len(paper.get('positions', {}))}\n"
    f"  * Market: closed (after 15:30 IST)\n\n"
    "Next: 08:25 IST tomorrow, the pre-market self-heal will fire automatically. "
    "Trade paper for 30 days. After 30d: /live enable to see the 9-gate status."
)

ok = send_telegram(msg)
print(f"telegram sent: ok={ok}")
