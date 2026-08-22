' mavis_app_wrapper.vbs
' Auto-restart wrapper for the Mavis desktop app.
' Drops to startup folder for boot-time recovery:
'   Copy-Item mavis_app_wrapper.vbs "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\"
' Runs powershell.exe hidden, which runs mavis_app_loop.ps1.
' If the desktop app crashes, the loop relaunches it within 30s.

Set WshShell = CreateObject("WScript.Shell")
strProjectRoot = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
strCmd = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & strProjectRoot & "\mavis_app_loop.ps1"""

' WshShell.Run: 0 = hidden window, False = don't wait for completion
WshShell.Run strCmd, 0, False
