@echo off
REM UNINSTALL.bat - one-click uninstaller (requires admin)
REM Right-click UNINSTALL.bat -> "Run as administrator"

echo =====================================================
echo  Uninstalling kotak-neo-bot daily automation
echo =====================================================
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\install_daily_tasks.ps1" -Uninstall
echo.
echo Done.
echo.
pause
