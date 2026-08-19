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
Day 10 (Wed 19 Aug 10:40 IST) — bot alive, market open.

8:30 daily-start cron fired, bot restarted, 2 procs healthy.
Dashboard UP :8501.
16 phantoms (12AUG/13AUG expiry) still blocking all SCAN entries — same as Day 9, +16 startup_reconcile orders on restart.
Capital: Rs.1,32,749.95 / realized Rs.5,597.55 / 188 orders / 16 positions (unchanged from Day 9 close).

Intraday cutoff 13:30. EOD report at 15:30.
Phantoms need manual action to unblock: (a) /force skip_reconcile, or (b) broker terminal close, or (c) wait for T+1 auto-settle.
"@

$msgFile = Join-Path $root 'scripts\msg_morning_day10.txt'
[System.IO.File]::WriteAllText($msgFile, $msg, [System.Text.Encoding]::UTF8)

$resp = curl.exe -s -X POST "https://api.telegram.org/bot$token/sendMessage" --data-urlencode "chat_id=$chatId" --data-urlencode "text@$msgFile"
Write-Host "Telegram resp: $resp"
