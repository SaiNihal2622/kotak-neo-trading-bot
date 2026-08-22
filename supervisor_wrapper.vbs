' supervisor_wrapper.vbs
' Auto-restart wrapper for the supervisor loop.
' Drops to startup folder for boot-time recovery:
'   Copy-Item supervisor_wrapper.vbs "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\"
' Runs powershell.exe hidden, which runs supervisor_loop.ps1 which runs kotak_supervisor.py.
' If ANY layer dies, the layer below re-launches it.

Set WshShell = CreateObject("WScript.Shell")
strProjectRoot = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
strCmd = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & strProjectRoot & "\supervisor_loop.ps1"""

' WshShell.Run: 0 = hidden window, False = don't wait for completion
WshShell.Run strCmd, 0, False
