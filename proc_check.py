"""Check if the bot main loop is actually running by inspecting memory/threads."""
import subprocess
import json
import urllib.request

LOG = open("proc_check.txt", "w", encoding="utf-8")
def o(m): LOG.write(m + "\n"); LOG.flush()

# 1. Check process state via PowerShell
r = subprocess.run(
    ["powershell", "-Command", "Get-Process python -ErrorAction SilentlyContinue | Select-Object Id, StartTime, CPU, WS, Threads | Format-List"],
    capture_output=True, text=True
)
o("=== Process info ===")
o(r.stdout)

# 2. Check paper state file
import os
p = "data_cache/paper_state.json"
if os.path.exists(p):
    s = json.load(open(p, encoding="utf-8"))
    o(f"\n=== Paper state ===")
    o(f"  cash: Rs.{s.get('cash', 0):,.0f}")
    o(f"  orders: {len(s.get('orders', {}))}")
    o(f"  positions: {len(s.get('positions', {}))}")
    o(f"  file mtime: {os.path.getmtime(p)}")
    import time
    o(f"  file age: {time.time() - os.path.getmtime(p):.1f} sec ago")
else:
    o("  no state file")

# 3. Check audit log
p2 = "data_cache/audit_log.jsonl"
if os.path.exists(p2):
    s = os.path.getsize(p2)
    o(f"\n=== Audit log: {s} bytes, mtime {os.path.getmtime(p2):.0f} ===")

# 4. Try to ping telegram bot
import os
token = os.getenv("TELEGRAM_BOT_TOKEN")
if not token:
    # try to load from .env
    for line in open("config/credentials.env", encoding="utf-8"):
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            token = line.split("=", 1)[1].strip()
            break

if token:
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates?timeout=2", timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        o(f"\n=== Telegram getUpdates: ok={data.get('ok')}, count={len(data.get('result', []))} ===")
    except Exception as e:
        o(f"\n=== Telegram getUpdates error: {e} ===")

# 5. Log file mtime
import os
p3 = "bot_stderr.log"
if os.path.exists(p3):
    o(f"\n=== bot_stderr.log: mtime {os.path.getmtime(p3):.0f}, size {os.path.getsize(p3)} bytes ===")
    import time
    o(f"   last write: {time.time() - os.path.getmtime(p3):.1f} sec ago")

LOG.close()
