@echo off
REM Start KotakCore - launched by scheduled task at boot
cd /d "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
".venv\Scripts\python.exe" -m system.core.api.server --db "data_cache\state.db" --port 8510 >> "Logs\core_stdout.log" 2>> "Logs\core_stderr.log"
