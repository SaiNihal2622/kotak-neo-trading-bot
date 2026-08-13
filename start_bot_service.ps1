# NSSM service installer for kotak-neo-bot
# Usage: .\start_bot_service.ps1 install   (requires Admin)
#        .\start_bot_service.ps1 remove
#        .\start_bot_service.ps1 status

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('install','remove','status')]
    [string]$Action
)

$ErrorActionPreference = 'Stop'
$ProjectDir  = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
$VenvPython  = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$DashboardPy = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$LogDir      = Join-Path $ProjectDir "logs"
$NSSM        = Join-Path $ProjectDir "tools\nssm.exe"
$BotService  = "KotakNeoBot"
$DashService = "KotakNeoDashboard"

function Ensure-NSSM {
    if (-not (Test-Path $NSSM)) {
        Write-Host "Downloading NSSM (portable)..."
        $NssmDir = Split-Path $NSSM
        New-Item -ItemType Directory -Force -Path $NssmDir | Out-Null
        $NssmZip = Join-Path $NssmDir "nssm.zip"
        # NSSM 2.24 from official mirror (portable Windows binary)
        Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $NssmZip -UseBasicParsing
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $Zip = [IO.Compression.ZipFile]::OpenRead($NssmZip)
        # Extract 64-bit version (Windows 11 is x64)
        $Entry = $Zip.Entries | Where-Object { $_.FullName -like "*win64*" -and $_.Name -eq "nssm.exe" } | Select-Object -First 1
        if ($null -eq $Entry) { $Entry = $Zip.Entries | Where-Object { $_.Name -eq "nssm.exe" } | Select-Object -First 1 }
        [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $NssmDir, $true)
        $Zip.Dispose()
        Remove-Item $NssmZip -Force
        if (-not (Test-Path $NSSM)) { throw "NSSM extraction failed" }
    }
    Write-Host "NSSM at: $NSSM"
}

function Install-BotService {
    Ensure-NSSM
    $Stdout = Join-Path $LogDir "bot_stdout.log"
    $Stderr = Join-Path $LogDir "bot_stderr.log"
    # remove existing if any
    & $NSSM stop $BotService 2>$null
    & $NSSM remove $BotService confirm 2>$null
    Start-Sleep 1
    & $NSSM install $BotService $VenvPython "-u -m kotak_bot paper"
    & $NSSM set $BotService AppDirectory $ProjectDir
    & $NSSM set $BotService AppStdout $Stdout
    & $NSSM set $BotService AppStderr $Stderr
    & $NSSM set $BotService AppRotateFiles 1
    & $NSSM set $BotService AppRotateBytes 10485760
    & $NSSM set $BotService DisplayName "Kotak Neo Trading Bot (paper)"
    & $NSSM set $BotService Description "Paper trading bot for NSE options, intraday-only, VIX-aware"
    & $NSSM set $BotService Start SERVICE_AUTO_START
    & $NSSM set $BotService AppRestartDelay 5000
    & $NSSM set $BotService AppThrottle 10000
    & $NSSM set $BotService ExitActions Restart
    & $NSSM set $BotService AppEnvironmentExtra "KOTAK_API_KEY=ab1c547b-17c0-4f48-ba4a-9a01e3c996b4`nKOTAK_ENV=uat`nKOTAK_MOBILE=+916305842166`nKOTAK_UCC=V6LC6`nKOTAK_MPIN=262204`nKOTAK_TOTP_SECRET=QQRKH23BKY52GS5A7DCSJIZIM4`nKOTAK_ALGO_ID=KOTAK_NEO_BOT_V1`nKOTAK_LIVE_CONFIRMED=NO`nPYTHONPATH=C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
    & $NSSM start $BotService
    Write-Host "Bot service installed and started. Use 'Get-Service $BotService' to check status."
}

function Install-DashboardService {
    Ensure-NSSM
    $Stdout = Join-Path $LogDir "dashboard_stdout.log"
    $Stderr = Join-Path $LogDir "dashboard_stderr.log"
    & $NSSM stop $DashService 2>$null
    & $NSSM remove $DashService confirm 2>$null
    Start-Sleep 1
    & $NSSM install $DashService $DashboardPy "-u -m streamlit run dashboard\app.py --server.port=8501 --server.headless=true"
    & $NSSM set $DashService AppDirectory $ProjectDir
    & $NSSM set $DashService AppStdout $Stdout
    & $NSSM set $DashService AppStderr $Stderr
    & $NSSM set $DashService AppRotateFiles 1
    & $NSSM set $DashService AppRotateBytes 10485760
    & $NSSM set $DashService DisplayName "Kotak Neo Dashboard (Streamlit :8501)"
    & $NSSM set $DashService Description "Streamlit dashboard for kotak-neo-bot"
    & $NSSM set $DashService Start SERVICE_AUTO_START
    & $NSSM set $DashService AppRestartDelay 5000
    & $NSSM set $DashService AppThrottle 10000
    & $NSSM set $DashService ExitActions Restart
    & $NSSM set $DashService AppEnvironmentExtra "PYTHONPATH=C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
    & $NSSM start $DashService
    Write-Host "Dashboard service installed and started."
}

function Remove-Services {
    Ensure-NSSM
    foreach ($svc in @($BotService, $DashService)) {
        & $NSSM stop $svc 2>$null
        & $NSSM remove $svc confirm 2>$null
        Write-Host "Removed service: $svc"
    }
}

function Show-Status {
    foreach ($svc in @($BotService, $DashService)) {
        $s = Get-Service $svc -ErrorAction SilentlyContinue
        if ($null -eq $s) { Write-Host "$svc: NOT INSTALLED" }
        else { Write-Host "$svc: $($s.Status) (StartType: $($s.StartType))" }
    }
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
        $_.CommandLine -like '*kotak_bot*' -or $_.CommandLine -like '*streamlit run dashboard*'
    }
    Write-Host "Python procs: $($procs.Count)"
    $procs | ForEach-Object {
        $age = (Get-Date) - $_.CreationDate
        Write-Host "  PID=$($_.ProcessId) age=$([int]$age.TotalMinutes)m cmd=$($_.CommandLine.Substring(0, [Math]::Min(80, $_.CommandLine.Length)))..."
    }
}

switch ($Action) {
    'install' {
        Install-BotService
        Install-DashboardService
        Show-Status
    }
    'remove'  { Remove-Services }
    'status'  { Show-Status }
}
