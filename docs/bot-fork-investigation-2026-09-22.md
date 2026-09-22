# 2026-09-22 Bot Fork Investigation

## Symptom
Every NSSM restart of KotakBotPaper results in TWO python processes running
both `python -m kotak_bot paper`. The "first" (NSSM-launched) is a 4 MB
idle launcher that spawns the "second" (525 MB active bot) within 1 second.

Parent chain observed:
```
NSSM (KotakBotPaper) -> powershell run_bot.ps1 -> venv python (4 MB) -> SYSTEM python (525 MB)
```

## Where the fork happens
**Unknown.** Exhaustive search of:
- All .py files in `kotak_bot/` for `subprocess.run`, `subprocess.Popen`,
  `multiprocessing.Process`, `os.execv`, `os.spawn*`
- `system/run_bot.ps1` (just calls `& $PythonExe -m kotak_bot paper` once)
- `kotak_bot/__main__.py` module-level imports (no spawners)
- pyvenv.cfg and sitecustomize.py (standard, no spawners)

No code path found that calls `python -m kotak_bot paper` from inside the bot.

## Working hypothesis
PATH has `C:\Program Files\Python312\` BEFORE the venv's Python, so any
`subprocess.Popen(["python", ...])` call from a venv-python subprocess would
resolve to the SYSTEM Python. If the bot has any hidden spawn that uses
`"python"` as the executable (without full path), it would land on the SYSTEM
Python and appear identical to the canonical bot.

## Mitigation
Two layers prevent this from being a problem:

1. **Orphan killer** (`scripts/orphan_killer.py`, commit 43af756)
   - Wired into `scripts/nssm_watchdog.py` (runs every 15 min via SYSTEM context)
   - Enumerates all `python -m kotak_bot paper` processes via PowerShell
     Get-CimInstance (works from SYSTEM context without psutil)
   - Kills any whose PID doesn't match `data_cache/paper.lock`
   - **5-min minimum uptime filter**: doesn't kill bots < 5 min old (mid-startup)
   - Pattern ONLY matches `-m kotak_bot paper` (NOT http_server or brain)

2. **Self-heal guard** (`kotak_bot/self_heal.py:_fix_nssm_service_stopped`,
   commit c9a0259)
   - Was calling `nssm start KotakBotPaper` whenever NSSM state was STOPPED
   - This caused a 2nd restart during NSSM AppThrottle window, creating duplicates
   - Now checks for OTHER running kotak_bot paper processes first
   - Skips the nssm start if any other bot is running (the STOPPED detection
     was a transient state during AppThrottle, not a real issue)

## Status (as of 2026-09-22 14:35)
- Bot IS trading, IS responding to brain, IS healthy
- The duplicate process exists but is harmless (orphan killer handles it)
- All 4 dashboard ports responding (8501/8502/8503/8504)
- Lock contention fixed (commit 804b631)
- Telegram gate fixed (commit a9a6e9c)
- LLM timeout retry added (commit 6fe9b86)
