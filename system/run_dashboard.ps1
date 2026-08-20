# =============================================================================
# run_dashboard.ps1 — NSSM service entry point for the Streamlit dashboard.
# =============================================================================
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$RepoRoot = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
$LogDir   = Join-Path $RepoRoot 'Logs'
$LogFile  = Join-Path $LogDir 'dashboard_stderr.log'
$OutFile  = Join-Path $LogDir 'dashboard_stdout.log'
$StreamlitExe = Join-Path $RepoRoot '.venv\Scripts\streamlit.exe'
$EnvFile   = Join-Path $RepoRoot '.env'

if (-not (Test-Path $LogDir)) {
  New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
if ((Test-Path $LogFile) -and (Get-Item $LogFile).Length -gt 50MB) {
  Move-Item -Path $LogFile -Destination "$LogFile.prev" -Force
}

Set-Location $RepoRoot
$env:DOTENV_PATH = $EnvFile
$env:PYTHONPATH = $RepoRoot

& $StreamlitExe run dashboard\app.py --server.port=8501 --server.headless=true --server.address=127.0.0.1
exit $LASTEXITCODE
