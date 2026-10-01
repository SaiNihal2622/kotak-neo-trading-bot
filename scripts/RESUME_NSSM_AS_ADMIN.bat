@echo off
REM ============================================================
REM  PHASE 12 - RESUME NSSM brain_daemon service as ADMIN
REM ============================================================
REM  Right-click this file and select "Run as administrator"
REM  (or in PowerShell: Start-Process -Verb RunAs)
REM
REM  This will:
REM    1. Resume the KotakBrainDaemon NSSM service from PAUSED state
REM    2. Set the service to start automatically
REM    3. Start the service in BRAIN_DAEMON_MODE=watchdog
REM    4. Verify the heartbeat is being written
REM
REM  The Mavis cron (kotak-mavis-brain-cycle-phase12) is the
REM  PRIMARY brain. This watchdog just confirms the Mavis
REM  cron is alive via heartbeat_mavis_brain.json freshness.
REM ============================================================

echo.
echo === PHASE 12 - NSSM Resume Script ===
echo.

REM Check admin
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: This script must be run as Administrator.
    echo Right-click the .bat file and select "Run as administrator"
    pause
    exit /b 1
)

set NSSM=C:\Tools\nssm\nssm-2.24\win64\nssm.exe

echo [1/4] Setting service to AUTO START...
"%NSSM%" set KotakBrainDaemon Start SERVICE_AUTO_START
if %ERRORLEVEL% NEQ 0 goto :error

echo [2/4] Resuming from PAUSED state...
"%NSSM%" continue-service KotakBrainDaemon
if %ERRORLEVEL% NEQ 0 goto :error

echo [3/4] Starting service...
"%NSSM%" start KotakBrainDaemon
if %ERRORLEVEL% NEQ 0 goto :error

echo [4/4] Checking status...
"%NSSM%" status KotakBrainDaemon

echo.
echo Service should be RUNNING in WATCHDOG mode.
echo Primary brain is Mavis cron (kotak-mavis-brain-cycle-phase12).
echo This watchdog only writes heartbeat + monitors Mavis cron.

timeout /t 5

echo.
echo Verifying heartbeat...
type C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\heartbeat_brain_daemon.json 2>nul

echo.
echo.
echo === DONE ===
pause
exit /b 0

:error
echo.
echo ERROR: NSSM command failed. Service may still be paused.
echo Try running each step manually:
echo   1. %NSSM% set KotakBrainDaemon Start SERVICE_AUTO_START
echo   2. %NSSM% continue-service KotakBrainDaemon
echo   3. %NSSM% start KotakBrainDaemon
pause
exit /b 1