$ErrorActionPreference = 'Stop'
$root = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
$credPath = Join-Path $root 'config\credentials.env'
Get-Content $credPath -Raw | ForEach-Object {
    $lines = $_ -split "`n"
    foreach ($line in $lines) {
        if ($line -match '^(TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID)=') {
            $kv = $line -split '=', 2
            Set-Item -Path "Env:\$($kv[0])" -Value $kv[1].Trim()
        }
    }
}
$token = $env:TELEGRAM_BOT_TOKEN
$chatId = $env:TELEGRAM_CHAT_ID

$msg = @"
Day 10 (Wed 19 Aug 13:40 IST) — CRITICAL

Bot just RESTARTED at 13:40:29 (fresh PID 26812 + liveness monitor). Old instance (PID 25956+26852 from 10:35:35, ~3h05m uptime) is gone.
Dashboard :8501 currently DOWN (port unreachable).

Intraday cutoff 13:30 already hit; new bot startup completed but dashboard supervisor may still be coming up.

16 phantoms persist (same as Day 9). Capital unchanged.

Will recheck dashboard in 30s. If dashboard stays down, may need manual streamlit restart.
"@

$msgFile = Join-Path $root 'scripts\msg_critical_1340.txt'
[System.IO.File]::WriteAllText($msgFile, $msg, [System.Text.Encoding]::UTF8)

$resp = curl.exe -s -X POST "https://api.telegram.org/bot$token/sendMessage" --data-urlencode "chat_id=$chatId" --data-urlencode "text@$msgFile"
Write-Host "Telegram resp: $resp"
