# mavis_app_loop.ps1
# Indefinite re-launcher for the MiniMax Code desktop app (Mavis UI).
# Checks every 30s if MiniMax Code.exe is running; if not, relaunches it.
# The desktop app is the user's UI entry point — when it crashes,
# the agent session is still alive on the server side, but the user
# can't see it. This loop brings the window back.
#
# Run with hidden window via mavis_app_wrapper.vbs at user logon.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$loopLog = Join-Path $logDir "mavis_app_loop.log"

$mavisExe = Join-Path $env:LOCALAPPDATA "Programs\MiniMax Code\MiniMax Code.exe"
if (-not (Test-Path $mavisExe)) {
    # Fallback: search common install paths
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\MiniMax Code\MiniMax Code.exe"),
        "C:\Program Files\MiniMax Code\MiniMax Code.exe",
        "C:\Program Files (x86)\MiniMax Code\MiniMax Code.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $mavisExe = $c; break }
    }
}

function Write-LoopLog([string]$msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$ts] $msg" | Out-File -FilePath $loopLog -Append -Encoding utf8
}

function Test-MavisRunning {
    # The exe name has a space in it, so use Get-CimInstance with Name filter
    try {
        $procs = Get-CimInstance Win32_Process -Filter "Name='MiniMax Code.exe'" -ErrorAction SilentlyContinue
        return ($procs -and $procs.Count -gt 0)
    } catch {
        return $false
    }
}

Write-LoopLog "mavis_app_loop: starting wrapper (pid=$PID, exe=$mavisExe)"

$pollIntervalSec = 30
$restartCooldownSec = 10  # don't restart twice within 10s
$maxConsecutiveFailures = 5
$lastRestartAt = 0.0
$consecutiveFailures = 0

while ($true) {
    if (-not (Test-MavisRunning)) {
        $now = [DateTime]::UtcNow
        $epochSec = ($now - [DateTime]"1970-01-01").TotalSeconds
        $elapsedSinceLast = $epochSec - $lastRestartAt
        if ($elapsedSinceLast -ge $restartCooldownSec) {
            # Check memory before attempting launch (avoids "paging file too small" errors)
            try {
                $os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
                $freeVmMb = if ($os) { [math]::Round($os.FreeVirtualMemory / 1MB, 0) } else { -1 }
                if ($freeVmMb -lt 50) {
                    Write-LoopLog ("mavis_app_loop: skipping relaunch - free VM only {0}MB (< 50MB threshold). Will retry on next tick." -f $freeVmMb)
                    $consecutiveFailures++
                } else {
                    Write-LoopLog ("mavis_app_loop: Mavis UI is DOWN (free VM={0}MB), relaunching ({1})" -f $freeVmMb, $mavisExe)
                    $proc = Start-Process -FilePath $mavisExe -PassThru -ErrorAction Stop
                    $lastRestartAt = $epochSec
                    $consecutiveFailures = 0
                    Write-LoopLog "mavis_app_loop: launched Mavis UI pid=$($proc.Id)"
                }
            }
            catch {
                $consecutiveFailures++
                Write-LoopLog ("mavis_app_loop: relaunch FAILED ({0}/{1}): {2}" -f $consecutiveFailures, $maxConsecutiveFailures, $_)
            }
        } else {
            Write-LoopLog "mavis_app_loop: Mavis UI still down, in cooldown ($([math]::Round($elapsedSinceLast,1))s of ${restartCooldownSec}s)"
        }
    } else {
        # Reset failure counter on successful tick
        if ($consecutiveFailures -gt 0) {
            Write-LoopLog ("mavis_app_loop: Mavis UI healthy again after {0} failures - reset" -f $consecutiveFailures)
            $consecutiveFailures = 0
        }
    }

    Start-Sleep -Seconds $pollIntervalSec
}
