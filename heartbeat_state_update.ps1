$statePath = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\heartbeat_state.json'
$stateDir = Split-Path $statePath -Parent
if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Path $stateDir -Force | Out-Null }
$state = @{
    err      = 0
    alive4   = 6
    aliveAll = 6
    dash     = 200
    mktHours = $false
    ts       = (Get-Date).ToString('o')
} | ConvertTo-Json
Set-Content -Path $statePath -Value $state -Encoding UTF8
Write-Host "state written to $statePath"
