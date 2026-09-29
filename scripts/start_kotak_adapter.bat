@echo off
REM Start KotakBotAdapter - launched by scheduled task at boot (after KotakCore)
cd /d "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
".venv\Scripts\python.exe" -m system.core.migration.bot_adapter --json "data_cache\paper_state.json" --db "data_cache\state.db" --interval 1 >> "Logs\adapter_stdout.log" 2>> "Logs\adapter_stderr.log"
