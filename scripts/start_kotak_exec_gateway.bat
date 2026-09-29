@echo off
REM Start KotakExecGateway - reads ORDER_PROPOSED events from /ws, places orders
REM Default: DRY-RUN mode (no real broker calls). Pass --live to enable.
cd /d "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
".venv\Scripts\python.exe" -m system.exec.exec_gateway --dry-run >> "Logs\exec_gateway_stdout.log" 2>> "Logs\exec_gateway_stderr.log"