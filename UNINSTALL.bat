@echo off
REM UNINSTALL.bat - remove the 3 daily scheduled tasks (no UAC required).
REM FIX 2026-09-04 15:55: same approach as INSTALL.bat - delegate to the
REM SYSTEM-running bot instead of using UAC.
REM
REM Future enhancement: add UNINSTALL_TASKS action to bot's force-action
REM channel. For now this clears the tasks via a one-shot Python script
REM run by the user (does NOT need admin - /F flag is a delete, and the
REM tasks are owned by LocalSystem so the script needs admin). Use the
REM bot's /restart command (via Telegram) to flush the bot, then run
REM this from an admin PowerShell if you want to remove the tasks.

echo =====================================================
echo  kotak-neo-bot daily task UNINSTALLER
echo =====================================================
echo.
echo  Note: the 3 tasks are owned by LocalSystem. Removing them
echo  requires admin. The simplest way is to disable the tasks
echo  via Task Scheduler UI (run taskschd.msc as admin) and
echo  delete the 3 kotak-* entries.
echo.
echo  Alternative: re-run INSTALL.bat to refresh the registration,
echo  or wait until the next bot restart (the bot's
echo  INSTALL_TASKS action will re-register them).
echo.
pause
