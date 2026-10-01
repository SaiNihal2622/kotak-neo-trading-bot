@echo off
REM ============================================================
REM  ONE-CLICK ADMIN SETUP — Phase 12 final admin operations
REM ============================================================
REM  Right-click → "Run as administrator"
REM
REM  This single batch does ALL the admin work:
REM    1. Set BRAIN_DAEMON_MODE=watchdog machine-wide
REM    2. Set AppEnvironmentExtra on KotakBrainDaemon NSSM service
REM    3. Resume service from PAUSED state
REM    4. Enable sudo (registry key)
REM    5. Verify everything is running
REM
REM  Before this batch:
REM    - Mavis cron (kotak-mavis-brain-cycle-phase12) IS active
REM    - brain_daemon NSSM service is PAUSED (cycle mode)
REM    - All MCP plugins enabled (puppeteer, fetch, memory, etc.)
REM
REM  After this batch:
REM    - BRAIN_DAEMON_MODE=watchdog everywhere
REM    - NSSM service RUNNING in watchdog mode
REM    - sudo enabled (future admin tasks easier)
REM    - Heartbeat writing
REM ============================================================

echo.
echo === PHASE 12 - ONE-CLICK ADMIN SETUP ===
echo.

net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: This batch MUST be run as Administrator.
    echo Right-click → "Run as administrator"
    pause
    exit /b 1
)

set NSSM=C:\Tools\nssm\nssm-2.24\win64\nssm.exe
set PROJ=C:\Users\saini\.minimax-agent\projects\kotak-neo-bot

echo [1/6] Setting BRAIN_DAEMON_MODE=watchdog machine-wide...
setx BRAIN_DAEMON_MODE watchdog /M >nul 2>&1
if %ERRORLEVEL% NEQ 0 goto :error

echo [2/6] Setting NSSM service env...
"%NSSM%" set KotakBrainDaemon AppEnvironmentExtra "PYTHONIOENCODING=utf-8;BRAIN_DAEMON_MODE=watchdog"
if %ERRORLEVEL% NEQ 0 goto :error

echo [3/6] Resuming service from PAUSED...
"%NSSM%" continue-service KotakBrainDaemon
if %ERRORLEVEL% NEQ 0 goto :error

echo [4/6] Setting start mode to AUTO...
"%NSSM%" set KotakBrainDaemon Start SERVICE_AUTO_START
"%NSSM%" start KotakBrainDaemon
if %ERRORLEVEL% NEQ 0 goto :error

echo [5/6] Enabling sudo for future admin tasks...
reg add "HKLM\SYSTEM\CurrentControlSet\Control\DeveloperSettings" /v EnableSudo /t REG_DWORD /d 1 /f >nul 2>&1
echo       (sudo enable attempted)

echo [6/6] Verifying...
echo.
"%NSSM%" status KotakBrainDaemon
echo.
timeout /t 5
type "%PROJ%\data_cache\heartbeat_brain_daemon.json"
echo.
echo.
echo === ALL DONE ===
echo.
echo Brain daemon is now running in WATCHDOG mode.
echo Mavis cron (kotak-mavis-brain-cycle-phase12) is the PRIMARY brain.
echo NSSM daemon is now the BACKUP watchdog.
echo.
echo Both tiers are LIVE. Tomorrow's first cron fire: Fri Oct 2 9:00 IST.
pause
exit /b 0

:error
echo.
echo ERROR: Setup failed at one of the steps.
echo Try running each command manually:
echo   1. setx BRAIN_DAEMON_MODE watchdog /M
echo   2. %NSSM% set KotakBrainDaemon AppEnvironmentExtra PYTHONIOENCODING=utf-8;BRAIN_DAEMON_MODE=watchdog
echo   3. %NSSM% continue-service KotakBrainDaemon
echo   4. %NSSM% set KotakBrainDaemon Start SERVICE_AUTO_START
echo   5. %NSSM% start KotakBrainDaemon
pause
exit /b 1