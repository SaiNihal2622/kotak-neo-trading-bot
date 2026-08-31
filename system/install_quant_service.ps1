$ErrorActionPreference = "Stop"
$py = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\.venv\Scripts\python.exe"
$script = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\scripts\quant_service.py"
$dir = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
$out = "$dir\Logs\quant_service.out.log"
$err = "$dir\Logs\quant_service.err.log"
mkdir "$dir\Logs" -Force | Out-Null

# Install
nssm install KotakQuantService $py "-u $script"
nssm set KotakQuantService AppDirectory $dir
nssm set KotakQuantService AppStdout $out
nssm set KotakQuantService AppStderr $err
nssm set KotakQuantService AppRotateFiles 1
nssm set KotakQuantService AppRotateBytes 10485760
nssm set KotakQuantService Start SERVICE_AUTO_START
nssm set KotakQuantService AppRestartDelay 5000
nssm set KotakQuantService AppStdoutCreationDisposition 2
nssm set KotakQuantService AppStderrCreationDisposition 2

# Start
nssm start KotakQuantService
Start-Sleep -Seconds 3

# Verify
$status = nssm status KotakQuantService
Write-Host "KotakQuantService status: $status"
Write-Host "HTTP control: http://127.0.0.1:8503"
Write-Host "Chat control: python scripts\quant_control.py {status|positions|decisions|pause|resume|close|ask}"
