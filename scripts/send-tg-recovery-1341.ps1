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
RESOLVED (13:41 IST) — Dashboard :8501 is back UP. Bot running normally.

State now:
- Bot: 2 procs healthy (new instance started 13:40:29, liveness monitor active)
- Dashboard: HTTP 200
- SCAN cycle 7: skip "intraday mode — no_new_trades_after (13:30) hit" (GATE SHIFT confirmed — time gate now dominant)
- Capital: Rs.1,32,749.95 / realized Rs.5,597.55 / 16 phantoms unchanged
- Startup reconcile: 16 positions (all 12AUG/13AUG expiry phantoms, no new fills)

Old bot (PID 25956+26852) had clean-exit death at ~3h05m uptime — recurring pattern. Investigating later.
"@

$msgFile = Join-Path $root 'scripts\msg_recovery_1341.txt'
[System.IO.File]::WriteAllText($msgFile, $msg, [System.Text.Encoding]::UTF8)

$resp = curl.exe -s -X POST "https://api.telegram.org/bot$token/sendMessage" --data-urlencode "chat_id=$chatId" --data-urlencode "text@$msgFile"
Write-Host "Telegram resp: $resp"
