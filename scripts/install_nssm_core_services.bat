@echo off
REM Install core + bot-adapter as NSSM services for auto-start.

set ROOT=C:\Users\saini\.minimax-agent\projects\kotak-neo-bot
set PYTHON=%ROOT%\.venv\Scripts\python.exe
set NSSM=C:\Tools\nssm\nssm-2.24\win32\nssm.exe

REM ----- KotakCore (FastAPI event-sourced trading core) -----
echo Installing KotakCore...
%NSSM% install KotakCore "%PYTHON%" "-m system.core.api.server --db %ROOT%\data_cache\state.db --port 8510"
%NSSM% set KotakCore AppDirectory "%ROOT%"
%NSSM% set KotakCore DisplayName "Kotak Trading Core"
%NSSM% set KotakCore Description "FastAPI event-sourced trading core (post-hoc risk, atomic plans)"
%NSSM% set KotakCore Start SERVICE_AUTO_START
%NSSM% set KotakCore AppStdout "%ROOT%\Logs\core_stdout.log"
%NSSM% set KotakCore AppStderr "%ROOT%\Logs\core_stderr.log"
%NSSM% set KotakCore AppRotateFiles 1
%NSSM% set KotakCore AppRotateBytes 10485760

REM ----- KotakBotAdapter (legacy JSON → core events bridge) -----
echo Installing KotakBotAdapter...
%NSSM% install KotakBotAdapter "%PYTHON%" "-m system.core.migration.bot_adapter --json %ROOT%\data_cache\paper_state.json --db %ROOT%\data_cache\state.db --interval 1"
%NSSM% set KotakBotAdapter AppDirectory "%ROOT%"
%NSSM% set KotakBotAdapter DisplayName "Kotak Bot JSON Adapter"
%NSSM% set KotakBotAdapter Description "Bridges legacy bot JSON to core event log (Phase 2)"
%NSSM% set KotakBotAdapter Start SERVICE_AUTO_START
%NSSM% set KotakBotAdapter AppStdout "%ROOT%\Logs\adapter_stdout.log"
%NSSM% set KotakBotAdapter AppStderr "%ROOT%\Logs\adapter_stderr.log"
%NSSM% set KotakBotAdapter AppRotateFiles 1
%NSSM% set KotakBotAdapter AppRotateBytes 10485760

REM ----- Start both -----
echo Starting services...
%NSSM% start KotakCore
%NSSM% start KotakBotAdapter

echo Done.
timeout /t 5 /nobreak
%NSSM% status KotakCore
%NSSM% status KotakBotAdapter