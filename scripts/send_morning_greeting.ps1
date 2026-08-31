$ErrorActionPreference = 'Stop'
$credFile = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\config\credentials.env"
$botToken = (Select-String -Path $credFile -Pattern '^TELEGRAM_BOT_TOKEN=(.+)$' | ForEach-Object { $_.Matches[0].Groups[1].Value }).Trim()
$chatId = (Select-String -Path $credFile -Pattern '^TELEGRAM_CHAT_ID=(.+)$' | ForEach-Object { $_.Matches[0].Groups[1].Value }).Trim()

if (-not $botToken -or -not $chatId) { Write-Error "Telegram creds missing"; exit 1 }

$msg = "Good morning. Bot is up. Market opens in 30 minutes. Use /status to check state."
$uri = "https://api.telegram.org/bot$botToken/sendMessage"
$body = @{ chat_id = $chatId; text = $msg }

try {
  $r = Invoke-RestMethod -Uri $uri -Method Post -Body $body -TimeoutSec 15
  if ($r.ok) {
    Write-Host "OK message_id=$($r.result.message_id) ts=$($r.result.date)"
  } else {
    Write-Host "FAIL response: $($r | ConvertTo-Json -Depth 3)"
    exit 2
  }
} catch {
  Write-Host "EXC: $($_.Exception.Message)"
  exit 3
}
