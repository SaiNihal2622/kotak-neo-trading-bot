$ErrorActionPreference = 'Stop'

# Load credentials
$credPath = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\config\credentials.env'
$env = @{}
Get-Content $credPath | ForEach-Object {
  if ($_ -match '^\s*#') { return }
  if ($_ -match '^\s*$') { return }
  $parts = $_ -split '=', 2
  if ($parts.Length -eq 2) {
    $k = $parts[0].Trim()
    $v = $parts[1].Trim()
    $env[$k] = $v
  }
}
$token = $env['TELEGRAM_BOT_TOKEN']
$chatId = $env['TELEGRAM_CHAT_ID']

$msg = @"
[OK] EOD daily report fired (first in 3.5 days since Fri Aug 14 outage).

Bot: ALIVE 7h00m | dashboard UP
SCAN: cycle 5009 (15:29:31) | tick 23436 (15:29:35)
Skip: intraday mode no_new_trades_after (13:30) hit
Capital: Rs.1,32,749.95 / realized Rs.5,597.55 / 172 orders
Positions: 0 internal, 16 broker_only 12AUG/13AUG phantoms (unchanged)
Compliance PDF: data_cache\compliance\compliance_2026-08-18.pdf (generated 15:30:04)

Day 9 paper trading: 0 new fills (blocked by intraday cutoff + phantoms).
Market closed. Bot will keep running for 15:45 EOD backup cron.
Next session: Wed Aug 19 09:00 IST (assume 16 phantoms persist).
"@

$msgFile = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\scripts\tmp_eod_1530_msg.txt'
Set-Content -Path $msgFile -NoNewline -Encoding UTF8 -Value $msg

$curlArgs = @(
  '-s'
  '-X', 'POST'
  "https://api.telegram.org/bot$token/sendMessage"
  '--data-urlencode', "chat_id=$chatId"
  '--data-urlencode', "text@$msgFile"
)
& curl.exe @curlArgs
Write-Host ""
Write-Host "DONE - EOD 15:30 Telegram sent"
