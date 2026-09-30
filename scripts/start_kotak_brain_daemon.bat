@echo off
REM Start KotakBrainDaemon - reads state, calls LLM, writes decisions to quant_actions.json
REM The existing BrainBridge then submits via /api/plan.
cd /d "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
".venv\Scripts\python.exe" -m system.brain.brain_daemon --interval 300 >> "Logs\brain_daemon_stdout.log" 2>> "Logs\brain_daemon_stderr.log"