@echo off
REM INSTALL.bat - one-click daily tasks installer (requires admin)
REM Right-click INSTALL.bat -> "Run as administrator"

echo =====================================================
echo  Installing kotak-neo-bot daily automation
echo =====================================================
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\install_daily_tasks.ps1" -Install
echo.
echo Done. 3 tasks installed (08:25 / 15:30 / 23:00 IST).
echo.
echo To uninstall: run UNINSTALL.bat as admin
echo.
pause
