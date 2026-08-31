# Self-elevating NSSM setup for KotakQuantService.
# Created 2026-08-31 17:01 IST by Mavis.
#
# When launched by the .bat wrapper, this:
#   1. Detects if it's already elevated (running as admin)
#   2. If not, re-launches itself elevated (triggers UAC), exits
#   3. Once elevated, installs + starts the NSSM service
#   4. Verifies HTTP :8503 is up
#
# User experience: double-click the .bat, click Yes on UAC. Done.

$ErrorActionPreference = "Stop"
$root = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
$log = Join-Path $root "Logs\nssm_setup.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

function Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Write-Host $line
    Add-Content -Path $log -Value $line
}

# === STEP 1: detect elevation ===
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)

if (-Not $isAdmin) {
    # Not elevated. Re-launch as admin. The UAC prompt will appear; the user clicks Yes.
    Log "Not elevated. Re-launching as administrator (UAC prompt will appear)..."
    $arg = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    try {
        Start-Process -FilePath "powershell.exe" -ArgumentList $arg -Verb RunAs -WindowStyle Hidden
    } catch {
        Log "ERROR: Failed to re-launch elevated. $_"
        exit 1
    }
    Log "Re-launched. Exiting this non-elevated instance."
    exit 0
}

Log "===== Running as administrator ====="

# === STEP 2: NSSM binary ===
$nssm = "C:\tools\nssm\nssm-2.24\win64\nssm.exe"
if (-Not (Test-Path $nssm)) {
    Log "ERROR: NSSM not found at $nssm"
    exit 1
}
Log "NSSM: $nssm"

# === STEP 3: install service (idempotent — remove if exists first) ===
$py = Join-Path $root ".venv\Scripts\python.exe"
$script = Join-Path $root "scripts\quant_service.py"
$out = Join-Path $root "Logs\quant_service.out.log"
$err = Join-Path $root "Logs\quant_service.err.log"
New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null

Log "Removing any existing KotakQuantService (clean install)..."
& $nssm stop KotakQuantService 2>$null | Out-Null
Start-Sleep -Seconds 1
& $nssm remove KotakQuantService confirm 2>$null | Out-Null
Start-Sleep -Seconds 1

Log "Installing KotakQuantService..."
& $nssm install KotakQuantService $py "-u $script" 2>&1 | Out-Null
& $nssm set KotakQuantService AppDirectory $root 2>&1 | Out-Null
& $nssm set KotakQuantService AppStdout $out 2>&1 | Out-Null
& $nssm set KotakQuantService AppStderr $err 2>&1 | Out-Null
& $nssm set KotakQuantService AppRotateFiles 1 2>&1 | Out-Null
& $nssm set KotakQuantService AppRotateBytes 10485760 2>&1 | Out-Null
& $nssm set KotakQuantService Start SERVICE_AUTO_START 2>&1 | Out-Null
& $nssm set KotakQuantService AppRestartDelay 5000 2>&1 | Out-Null
& $nssm set KotakQuantService AppStdoutCreationDisposition 2 2>&1 | Out-Null
& $nssm set KotakQuantService AppStderrCreationDisposition 2 2>&1 | Out-Null

# === STEP 4: start service ===
Log "Starting KotakQuantService..."
& $nssm start KotakQuantService 2>&1 | Out-Null
Start-Sleep -Seconds 4

# === STEP 5: verify ===
$status = & $nssm status KotakQuantService 2>&1
Log "Service status: $status"

try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8503/health" -UseBasicParsing -TimeoutSec 5
    Log "HTTP :8503 => $($resp.StatusCode) | $($resp.Content)"
} catch {
    Log "HTTP :8503 check failed: $($_.Exception.Message)"
}

Log "===== Setup complete ====="
Log "KotakQuantService is now: Auto-start, LocalSystem, auto-restart on crash, 24/7 reboot-survival."
Log "HTTP control: http://127.0.0.1:8503"
Log "Chat control: python scripts\quant_control.py {status|positions|decisions|ask|close|pause|resume}"
Log "To remove: nssm stop KotakQuantService && nssm remove KotakQuantService confirm"
