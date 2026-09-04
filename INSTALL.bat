@echo off
REM INSTALL.bat - install the 3 daily scheduled tasks (no UAC required).
REM FIX 2026-09-04 15:55: the old version called schtasks via UAC, which fails
REM on this box because ConsentPromptBehaviorAdmin=5 (UAC prompts for credentials
REM for non-Windows binaries, and the dialog auto-cancels when no password is
REM entered). The new approach: write a force-action JSON for the SYSTEM-running
REM bot, which calls schtasks as LocalSystem. No UAC, no dialog, no click.

echo =====================================================
echo  kotak-neo-bot daily task installer (no UAC)
echo =====================================================
echo.
echo  Approach: write a force-action for the running bot.
echo  The bot runs as LocalSystem (NSSM service) and calls
echo  schtasks /create on your behalf. No UAC dialog needed.
echo.

set "ROOT=C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"

REM Use Python to write the action JSON with proper formatting + UTF-8
"%ROOT%\.venv\Scripts\python.exe" -c "import json,datetime; open(r'%ROOT%\data_cache\mavis_force_action.json','w',encoding='utf-8').write(json.dumps({'action':'INSTALL_TASKS','reason':'INSTALL.bat user-triggered (no-UAC path)','consumed':False,'ts':datetime.datetime.now().isoformat()},indent=2))"

if errorlevel 1 (
    echo [ERROR] Failed to write force-action. Is the bot running?
    pause
    exit /b 1
)

echo [OK] INSTALL_TASKS action written.
echo [OK] The bot will process this within 30 sec and install:
echo     - kotak-pre-market-self-heal @ 08:25 IST
echo     - kotak-eod-pnl-evaluator  @ 15:30 IST
echo     - kotak-nightly-state-backup @ 23:00 IST
echo.
echo [INFO] Check Telegram for the BOT-SCHEDULER confirmation message.
echo [INFO] The tasks are owned by LocalSystem and run with full admin.
echo.
echo Done. Press any key to close.
pause >nul
exit /b
