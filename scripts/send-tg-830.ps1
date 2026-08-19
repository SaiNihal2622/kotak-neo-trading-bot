$ErrorActionPreference = 'Stop'
$envPath = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\config\credentials.env'
$content = Get-Content $envPath -Raw
$token = (Select-String -InputObject $content -Pattern 'TELEGRAM_BOT_TOKEN=(.+)' -AllMatches).Matches[0].Groups[1].Value.Trim()
$chat = (Select-String -InputObject $content -Pattern 'TELEGRAM_CHAT_ID=(.+)' -AllMatches).Matches[0].Groups[1].Value.Trim()
$msg = "[24/7 WATCHDOG 08:30 IST] CRITICAL: Tue 8:30 daily-start cron check. Bot STILL down (WMI_STRICT_BOT=0). Log 5177min stale (~86.3h, last write Fri 18:13 IST). Dashboard :8501 UP. Market opens in 30min. If cron fired it did not start the bot. Manual action: cd C:\Users\saini\.minimax-agent\projects\kotak-neo-bot; .venv\Scripts\python.exe -m kotak_bot paper"
$url = "https://api.telegram.org/bot$token/sendMessage"
$body = @{ chat_id = $chat; text = $msg }
$resp = curl.exe -s -X POST $url --data-urlencode "chat_id=$chat" --data-urlencode "text=$msg"
Write-Output "TELEGRAM_RESPONSE: $resp"
