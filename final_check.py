"""Final pre-sleep system check. Logs to file."""
import subprocess
import json
import urllib.request
from pathlib import Path
from datetime import datetime

LOG = open("final_check.txt", "w", encoding="utf-8")
def o(m): LOG.write(m + "\n"); LOG.flush()

o(f"=== FINAL CHECK @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')} ===")
o("")

# 1. Power plan
r = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True)
o(f"[1] Power plan: {r.stdout.strip()}")

# 2. Python processes
r = subprocess.run(["powershell", "-Command", "Get-Process python -ErrorAction SilentlyContinue | Select-Object Id, StartTime | Format-Table -AutoSize"], capture_output=True, text=True)
o(f"[2] Python processes:\n{r.stdout}")

# 3. Dashboard
try:
    with urllib.request.urlopen("http://localhost:8501/_stcore/health", timeout=5) as resp:
        o(f"[3] Dashboard health: {resp.status} OK")
except Exception as e:
    o(f"[3] Dashboard: DOWN - {e}")

# 4. Telegram
env = Path("config/credentials.env").read_text(encoding="utf-8")
for line in env.splitlines():
    if "TELEGRAM_CHAT_ID" in line:
        o(f"[4] Telegram: {line}")
        break

# 5. Bot log tail
try:
    log = Path("bot_stderr.log").read_text(encoding="utf-8", errors="ignore")
    lines = log.splitlines()[-5:]
    o(f"[5] Last 5 bot log lines:")
    for l in lines:
        # strip ANSI codes
        import re
        clean = re.sub(r'\x1b\[[0-9;]*m', '', l).replace('\u20b9', 'Rs.')
        o(f"    {clean}")
except Exception as e:
    o(f"[5] log read failed: {e}")

# 6. Errors check
o("[6] Recent errors (last 50 lines):")
try:
    log = Path("bot_stderr.log").read_text(encoding="utf-8", errors="ignore")
    err_lines = [l for l in log.splitlines()[-50:] if 'Traceback' in l or 'FATAL' in l or 'CRITICAL' in l]
    if err_lines:
        for l in err_lines:
            o(f"    {l[:200]}")
    else:
        o("    none")
except Exception as e:
    o(f"    check failed: {e}")

# 7. Paper state
o("[7] Paper state:")
try:
    s = json.loads(Path("data_cache/paper_state.json").read_text(encoding="utf-8"))
    o(f"    cash: Rs.{s.get('cash', 0):,.0f}")
    o(f"    orders: {len(s.get('orders', {}))}")
    o(f"    positions: {len(s.get('positions', {}))}")
    o(f"    realized_pnl: Rs.{s.get('realized_pnl', 0):,.0f}")
except Exception as e:
    o(f"    state read failed: {e}")

# 8. Crons
o("[8] Crons (via subprocess):")
r = subprocess.run(["mavis", "cron", "list"], capture_output=True, text=True)
for line in r.stdout.splitlines():
    if "kotak" in line.lower():
        o(f"    {line.strip()[:150]}")

o("")
o("=== ALL CHECKS COMPLETE ===")
LOG.close()
