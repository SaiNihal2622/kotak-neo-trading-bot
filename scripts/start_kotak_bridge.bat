@echo off
REM Start KotakBrainBridge - reads quant_actions.json, submits via /api/plan
cd /d "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
".venv\Scripts\python.exe" -m system.bridge.brain_bridge --interval 5 >> "Logs\bridge_stdout.log" 2>> "Logs\bridge_stderr.log"