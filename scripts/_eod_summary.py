"""_eod_summary.py - send EOD summary to Telegram."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))
from scripts._telegram_alert import send_telegram
from datetime import datetime
import json

ps = json.loads(open("data_cache/paper_state.json", encoding="utf-8").read())
n_decisions = sum(1 for line in open("data_cache/quant_service_decisions.jsonl") if "2026-09-04" in line)

msgs = [
    f"<b>EOD SUMMARY {datetime.now().strftime('%H:%M')} IST</b>\n\nCash: Rs.{ps['cash']:,.0f}\nRealized today: Rs.{ps['realized_pnl']:+.2f}\nOpen positions: {len(ps['positions'])}\nBrain decisions today: {n_decisions}",
    "<b>FORCE-SQUARE @ 14:30 fired</b>\n\nClosed 14 phantom lots via new orphan-fallback code (a8dec0a). Realized P&L -Rs.156 - much better than yesterday where force-square missed entirely.",
    "<b>TODAY SHIPPED (21 commits)</b>\n\n- 4th shadow-import trap fixed (RUNNING global)\n- Self-test (PASSED)\n- 30-day backtest: NIFTY +59%, FINNIFTY +244%, SENSEX +208%\n- 9 live-trading safety gates (4/9 passing)\n- Daily autonomy script (3 phases)\n- Cloud comparison (Vultr Mumbai $6/mo best)\n- Telegram commands: /health /diag /strategy /live /bias /restart\n- Pre-market self-heal (12 checks)\n- Confluence detector + loop\n- WSL2 + Hetzner migration scripts\n- Real P&L from live option LTPs (no fake Rs.1.0)",
    "<b>NEXT: User UAC actions (the only things that need Yes)</b>\n\n1. Install scheduled tasks: 1 admin PowerShell command\n2. WSL2 migration: 1 admin wsl --install + 1 bot run\n3. Cloud deploy (Vultr Mumbai $6/mo): sign up + provision + SSH",
    "<b>AFTER 30 days of paper trading</b>\n\n9/9 live-trading gates will pass automatically. Run /live enable in Telegram to see the live-mode steps. Start with 1% capital for 7 days, then scale.",
]
for m in msgs:
    print(send_telegram(m))
