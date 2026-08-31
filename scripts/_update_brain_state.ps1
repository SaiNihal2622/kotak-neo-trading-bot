$ErrorActionPreference = 'Stop'
$statePath = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json'
$actionsPath = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_actions.json'

$j = Get-Content $statePath -Raw | ConvertFrom-Json
$actions = Get-Content $actionsPath -Raw | ConvertFrom-Json

$j.call_count_today = 3
$j.last_decision = $actions

$j | ConvertTo-Json -Depth 20 | Set-Content -Path $statePath -Encoding UTF8
Write-Output "OK call_count_today=$($j.call_count_today)"
