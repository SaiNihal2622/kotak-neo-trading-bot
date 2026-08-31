# Self-launching wrapper for quant_watchdog.
# The .bat in shell:startup fires this at user logon.
# We launch the actual watchdog in a hidden window and exit.
# If the watchdog dies, the user can re-launch manually.

$ErrorActionPreference = "SilentlyContinue"
$root = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
$py = Join-Path $root ".venv\Scripts\python.exe"
$wd = Join-Path $root "scripts"
$logDir = Join-Path $root "Logs"
$out = Join-Path $logDir "quant_watchdog.out.log"
$err = Join-Path $logDir "quant_watchdog.err.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# Avoid duplicate: if watchdog is already running, exit.
$existing = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'quant_watchdog' }).Count
if ($existing -gt 0) {
    exit 0
}

# Launch detached. -WindowStyle Hidden + no parent shell visible.
$args = @('-u', 'quant_watchdog.py')
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $py
$psi.WorkingDirectory = $wd
foreach ($a in $args) { [void]$psi.ArgumentList.Add($a) }
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
[void][System.Diagnostics.Process]::Start($psi)
