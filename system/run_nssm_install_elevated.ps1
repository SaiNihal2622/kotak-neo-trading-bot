# Elevated NSSM install for KotakQuantService.
# Run with: powershell -Verb RunAs -File <this-script>
# (The launcher in the chat invokes it this way.)

$ErrorActionPreference = "Stop"
$py   = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\.venv\Scripts\python.exe"
$script = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\scripts\quant_service.py"
$dir  = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
$out  = "$dir\Logs\quant_service.out.log"
$err  = "$dir\Logs\quant_service.err.log"
$NSSM = "C:\tools\nssm\nssm-2.24\win64\nssm.exe"

New-Item -ItemType Directory -Force -Path "$dir\Logs" | Out-Null

# Remove existing if present
& $NSSM stop KotakQuantService 2>$null
& $NSSM remove KotakQuantService confirm 2>$null
Start-Sleep -Seconds 2

# Install
& $NSSM install KotakQuantService $py "-u $script" 2>&1
& $NSSM set KotakQuantService AppDirectory $dir
& $NSSM set KotakQuantService AppStdout $out
& $NSSM set KotakQuantService AppStderr $err
& $NSSM set KotakQuantService AppRotateFiles 1
& $NSSM set KotakQuantService AppRotateBytes 10485760
& $NSSM set KotakQuantService Start SERVICE_AUTO_START
& $NSSM set KotakQuantService AppRestartDelay 5000
& $NSSM set KotakQuantService AppStdoutCreationDisposition 2
& $NSSM set KotakQuantService AppStderrCreationDisposition 2

# Start
& $NSSM start KotakQuantService
Start-Sleep -Seconds 4

# Verify
$status = & $NSSM status KotakQuantService
Write-Host "KotakQuantService: $status"
Write-Host "HTTP control: http://127.0.0.1:8503"
Write-Host "Logs: $out | $err"
Write-Host "Chat control: python scripts\quant_control.py {status|positions|decisions|ask|close|pause|resume}"
